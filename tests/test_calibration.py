from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from compass.calibration import calibrate, load_sweeps, split_repositories
from compass.retrieval import Routing, upgrade_reasons


GRID = {"min_relevance": [0, 1], "min_overlap": [0], "max_entropy": [1], "max_files": [1000]}


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = []
        for number in range(4):
            directory = self.root / f"repo-{number}"
            directory.mkdir()
            report = {"benchmark_format": "SWE-Explore reference sweep", "repository_id": f"org/repo-{number}",
                      "instance_id": f"issue-{number}", "base_commit": "a" * 40, "routing": asdict(Routing()),
                      "index_metadata": {"embedding": {"provider": "hash"}, "dimensions": 8, "parser": "python-ast", "index_ref": f"index-{number}"},
                      "model": {"class": "Scripted", "name": "fixture"}, "limits_per_run": {"max_tokens": 1000}, "repeats": 2}
            path = directory / "sweep.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            self.paths.append(path)
            signals = {"lexical_hits": 1, "vector_hits": 1, "top_relevance": 0.3, "score_entropy": 0.5,
                       "channel_overlap": 0.5, "file_span": 1}
            runs = []
            for repeat in range(2):
                for mode, recall in (("t0", 0), ("t1", 0.25), ("t2", 0.75)):
                    runs.append({"repeat": repeat, "mode": mode, "line_budget": 100, "status": "passed", "result": {
                        "complete": True, "index_ref": f"index-{number}", "signals": signals,
                        "tier": mode.upper(), "routing": {"mode_status": "completed" if mode == "t2" else "not_needed"},
                        "instance_id": f"issue-{number}", "base_commit": "a" * 40, "line_budget": 100,
                        "predictions": [] if mode == "t0" else [{"path": "api.py", "start": 1, "end": 3}],
                        "metrics": {"line_recall": recall}, "elapsed_seconds": 1 if mode != "t2" else 3,
                        "usage": {"tokens": 50 if mode == "t2" else 0, "model_calls": int(mode == "t2"),
                                  "tool_calls": 2, "vector_queries": 1}}})
            (directory / "runs.jsonl").write_text("\n".join(json.dumps(run) for run in runs), encoding="utf-8")

    def change_runs(self, path, transform):
        raw_path = path.parent / "runs.jsonl"
        rows = [json.loads(line) for line in raw_path.read_text().splitlines()]
        transform(rows)
        raw_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    def run_calibration(self, directory="result", **kwargs):
        return calibrate(self.paths, self.root / directory, line_budget=100, grid=GRID, **kwargs)

    def test_repository_split_and_heldout_labels_do_not_change_selected_threshold(self):
        first = self.run_calibration()
        self.assertEqual(first["selected_routing"]["min_relevance"], 1)
        self.assertFalse(set(first["development"]["repositories"]) & set(first["holdout"]["repositories"]))
        holdout = set(first["holdout"]["repositories"])
        for path in self.paths:
            report = json.loads(path.read_text())
            if report["repository_id"] in holdout:
                def transform(rows):
                    for row in rows:
                        if row["mode"] == "t2":
                            row["result"]["metrics"]["line_recall"] = 0
                self.change_runs(path, transform)
        second = self.run_calibration("second")
        self.assertEqual(first["selected_routing"], second["selected_routing"])
        self.assertEqual(first["development"], second["development"])
        self.assertNotEqual(first["holdout"], second["holdout"])

    def test_upgrade_rate_cap_is_applied_only_on_development(self):
        result = self.run_calibration(max_upgrade_rate=0)
        self.assertEqual(result["selected_routing"]["min_relevance"], 0)
        self.assertEqual(result["development"]["repository_mean_upgrade_rate"], 0)
        self.assertEqual(result["development"]["query_mean_cost"]["tokens"], 0)

    def test_different_symbol_caps_cannot_be_mixed_for_calibration(self):
        report = json.loads(self.paths[0].read_text())
        report["symbol_line_cap"] = 64
        self.paths[0].write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "different"):
            load_sweeps(self.paths, 100)

    def test_deferred_pair_and_duplicate_instance_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_sweeps(self.paths + [self.paths[0]], 100)
        self.change_runs(self.paths[0], lambda rows: rows[0].update(status="deferred_escalation"))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.run_calibration()

    def test_mixed_embedding_and_missing_pairs_are_rejected(self):
        report = json.loads(self.paths[0].read_text())
        report["index_metadata"]["embedding"] = {"provider": "ollama", "model": "different"}
        self.paths[0].write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "different"):
            self.run_calibration()
        with self.assertRaisesRegex(ValueError, "paired"):
            load_sweeps(self.paths[1:], 200)

    def test_t0_bypass_is_preserved_and_repetitions_not_counted_as_instances(self):
        for path in self.paths:
            def transform(rows):
                for row in rows:
                    if row["mode"] == "t0":
                        row["result"]["predictions"] = [{"path": "api.py", "start": 1, "end": 1}]
                        row["result"]["metrics"]["line_recall"] = 1
            self.change_runs(path, transform)
        result = self.run_calibration()
        self.assertEqual(result["development"]["instances"] + result["holdout"]["instances"], 4)
        self.assertEqual(result["holdout"]["repository_mean_recall"], 1)
        self.assertEqual(result["holdout"]["repository_mean_upgrade_rate"], 0)

    def test_insufficient_groups_and_existing_output_fail(self):
        with self.assertRaisesRegex(ValueError, "three"):
            split_repositories([{"repository": "org/one"}])
        self.run_calibration()
        with self.assertRaises(FileExistsError):
            self.run_calibration()

    def test_exported_routing_reuses_online_gate(self):
        result = self.run_calibration()
        routing = Routing(**json.loads((self.root / "result/routing.json").read_text()))
        samples, _, _ = load_sweeps(self.paths, 100)
        self.assertEqual(bool(upgrade_reasons(samples[0]["signals"], True, routing)), True)
        self.assertFalse(result["public_benchmark_verified"])

    def test_case_aliases_cannot_cross_repository_split(self):
        report = json.loads(self.paths[1].read_text())
        report["repository_id"] = "ORG/REPO-0"
        report["instance_id"] = "other-issue"
        self.paths[1].write_text(json.dumps(report))
        self.change_runs(self.paths[1], lambda rows: [row["result"].update(instance_id="other-issue") for row in rows])
        samples, _, _ = load_sweeps(self.paths, 100)
        development, holdout = split_repositories(samples)
        self.assertFalse({row["repository"] for row in development} & {row["repository"] for row in holdout})
        aliases = [row for row in development if row["repository"] == "org/repo-0"]
        aliases += [row for row in holdout if row["repository"] == "org/repo-0"]
        self.assertEqual(len(aliases), 2)
