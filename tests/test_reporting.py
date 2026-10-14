import json
from pathlib import Path
import tempfile
import unittest

from compass.reporting import comparisons, write_report


def metrics(recall, seconds, tokens=0, **extra):
    return {"queries": 3, "mean_recall": recall, "mean_ndcg": recall, "mean_hit_file": recall,
            "mean_seconds": seconds, "mean_tokens": tokens, "mean_model_calls": 0,
            "mean_tool_calls": 1, "mean_vector_queries": 0, "failures": 0,
            "deferred_escalations": 0, "incomplete_explorations": 0, **extra}


class ReportingTests(unittest.TestCase):
    def fixture(self):
        return {"summary": {"cheap": metrics(0.5, 1), "better": metrics(0.8, 2),
                            "dominated": metrics(0.4, 3), "unavailable": metrics(1, 0, deferred_escalations=1)},
                "dataset_sources": ["synthetic-test"], "index_ref": "test-ref", "metric_scope": "file relevance",
                "public_benchmark_verified": False}

    def test_dominated_and_unexecuted_modes_are_excluded(self):
        result = comparisons(self.fixture())
        self.assertEqual(result["frontiers"]["mean_recall"]["mean_seconds"], ["cheap", "better"])
        self.assertFalse(next(row for row in result["rows"] if row["mode"] == "unavailable")["eligible"])

    def test_equal_cost_prefers_higher_quality_but_keeps_exact_ties(self):
        report = self.fixture()
        report["summary"] = {"a": metrics(0.8, 1), "b": metrics(0.8, 1), "c": metrics(0.7, 1)}
        result = comparisons(report)
        self.assertEqual(result["frontiers"]["mean_recall"]["mean_seconds"], ["a", "b"])

    def test_nonfinite_or_out_of_range_metrics_rejected(self):
        for key, value in (("mean_seconds", float("nan")), ("mean_recall", 1.1)):
            with self.subTest(key=key):
                report = self.fixture()
                report["summary"]["cheap"][key] = value
                with self.assertRaises(ValueError):
                    comparisons(report)

    def test_exports_are_reviewable_and_do_not_overwrite_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report"
            result = write_report(self.fixture(), target)
            self.assertEqual(len(result["files"]), 3)
            self.assertIn("synthetic-test", (target / "report.md").read_text())
            self.assertFalse(json.loads((target / "frontiers.json").read_text())["public_benchmark_verified"])
            self.assertIn("mean_recall", (target / "comparison.csv").read_text())
            with self.assertRaises(FileExistsError):
                write_report(self.fixture(), target)


if __name__ == "__main__":
    unittest.main()
