import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compass.budget_ablation import replay


class BudgetReplayTests(unittest.TestCase):
    def fixture(self, root):
        directory = root / "instance-001/sweep"
        directory.mkdir(parents=True)
        (directory.parent / "instance.jsonl").write_text("{}\n")
        (directory / "sweep.json").write_text(json.dumps({"instance_id": "one", "base_commit": "a" * 40}))
        candidates = [{"rank": 1, "id": "n", "path": "noise.py", "start": 1, "end": 50},
                      {"rank": 2, "id": "t", "path": "target.py", "start": 1, "end": 100}]
        rows = [{"mode": "t1", "repeat": repeat, "line_budget": 10, "status": "passed",
                 "result": {"candidates": candidates}} for repeat in (0, 1)]
        (directory / "runs.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
        source = root / "result.json"
        source.write_text(json.dumps({"all_passed": True, "instances": [{"instance_id": "one",
            "repository_id": "org/repo", "snapshot": str(root), "measurements": [{"ranking": "rrf",
            "sweep": str(directory / "sweep.json"), "summary": [{"mode": "t1", "line_budget": 10, "eligible": True}]}]}]}))
        instance = {"id": "one", "base_commit": "a" * 40, "core_regions": [{"path": "target.py", "start": 1, "end": 100}],
                    "optional_regions": [], "core_files": ["target.py"]}
        return source, instance

    def test_fixed_candidates_budget_effect_and_repetitions_do_not_add_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, instance = self.fixture(root)
            with patch("compass.budget_ablation.load_swe_instance", return_value=instance):
                report = replay(source, root / "output", budgets=(10, 30), caps=(10,))
                with self.assertRaises(FileExistsError):
                    replay(source, root / "output", budgets=(10, 30), caps=(10,))
            low, high = report["summary"]
            self.assertEqual(low["line_recall"], 0)
            self.assertEqual(high["line_recall"], .1)
            self.assertEqual(high["line_precision"], .5)
            self.assertEqual(high["instances"], 1)
            self.assertEqual(report["new_model_calls"], 0)
            self.assertEqual(len(report["records"]), 4)

    def test_ineligible_source_repetitions_are_excluded_as_a_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, instance = self.fixture(root)
            saved = json.loads(source.read_text())
            saved["instances"][0]["measurements"][0]["summary"][0]["eligible"] = False
            source.write_text(json.dumps(saved))
            with patch("compass.budget_ablation.load_swe_instance", return_value=instance):
                report = replay(source, root / "output")
            self.assertEqual(report["summary"], [])
            self.assertEqual(len(report["excluded"]), 2)
