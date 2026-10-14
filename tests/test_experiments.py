import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compass.benchmarks import file_digest
from compass.experiments import load_manifest, run_core_batch, select_queries


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.entries = []
        for name, queries, text in [("a", ["a1"], "invoice"), ("b", ["b1", "b2", "b3"], "absent")]:
            directory = self.root / name
            directory.mkdir()
            rows = {"corpus.jsonl": [{"_id": "doc", "text": "invoice"}],
                    "queries.jsonl": [{"_id": q, "text": text} for q in queries],
                    "qrels.jsonl": [{"query_id": q, "corpus_id": "doc", "score": 1} for q in queries]}
            for file, data in rows.items():
                (directory / file).write_text("\n".join(json.dumps(row) for row in data), encoding="utf-8")
            self.entries.append({"name": name, "data_dir": name, "level": 2, "revision": "synthetic-v1"})
        self.manifest = self.root / "manifest.json"
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps({"version": 1, "benchmark": "core", "datasets": self.entries}), encoding="utf-8")

    def run_batch(self, **kwargs):
        return run_core_batch(self.manifest, self.root / "results", **kwargs)

    def test_repetitions_do_not_multiply_quality_samples_and_means_are_distinct(self):
        result = self.run_batch(repeats=2)
        self.assertTrue(result["all_passed"])
        self.assertEqual(result["summary"]["queries"], 4)
        self.assertEqual(result["summary"]["query_weighted_mean"]["recall_at_100"], 0.25)
        self.assertEqual(result["summary"]["repository_mean"]["recall_at_100"], 0.5)
        self.assertEqual(len(list((self.root / "results").glob("dataset-*.json"))), 4)
        self.assertFalse(result["public_benchmark_verified"])

    def test_sampling_is_seeded_order_independent_and_does_not_use_labels(self):
        queries = {str(i): "query" for i in range(20)}
        selected = select_queries(queries, 5, 7, "repo")
        self.assertEqual(selected, select_queries(dict(reversed(list(queries.items()))), 5, 7, "repo"))
        self.assertNotEqual(selected, select_queries(queries, 5, 8, "repo"))
        result = self.run_batch(repeats=1, max_queries=1, seed=7)
        self.assertEqual(result["summary"]["queries"], 2)
        self.assertEqual(result["datasets"][1]["available_queries"], 3)

    def test_bad_pins_produce_visible_partial_failure(self):
        self.entries[0]["sha256"] = {"corpus.jsonl": "0" * 64}
        self.write_manifest()
        result = self.run_batch(repeats=1)
        self.assertFalse(result["all_passed"])
        self.assertEqual(result["summary"]["failed_datasets"], 1)
        self.assertEqual(result["summary"]["queries"], 3)
        self.assertIn("Pinned", result["datasets"][0]["error"])

    def test_complete_pins_and_no_overwrite(self):
        for entry in self.entries:
            entry["sha256"] = {path.name: file_digest(path) for path in (self.root / entry["data_dir"]).iterdir()}
        self.write_manifest()
        result = self.run_batch(repeats=1)
        self.assertTrue(all(row["hashes_pinned"] for row in result["datasets"]))
        with self.assertRaises(FileExistsError):
            self.run_batch(repeats=1)

    def test_duplicate_directory_aliases_are_rejected(self):
        self.entries[1]["data_dir"] = "a/../a"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_manifest(self.manifest)

    def test_changed_inputs_during_evaluation_fail(self):
        from compass.experiments import evaluate_core
        def changed(dataset):
            result = evaluate_core(dataset)
            path = Path(next(iter(dataset.provenance["files"])))
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            return result
        with patch("compass.experiments.evaluate_core", side_effect=changed):
            result = self.run_batch(repeats=1)
        self.assertFalse(result["all_passed"])
        self.assertNotIn("query_weighted_mean", result["summary"])

    def test_cli_returns_failure_for_partial_batch(self):
        from compass.cli import main
        self.entries[0]["sha256"] = {"corpus.jsonl": "0" * 64}
        self.write_manifest()
        with patch("builtins.print"):
            self.assertEqual(main(["benchmark", "core-batch", "--manifest", str(self.manifest),
                                   "--output-dir", str(self.root / "results"), "--repeats", "1"]), 1)
