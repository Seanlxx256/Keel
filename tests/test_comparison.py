import unittest
import contextlib
import io
import json
from pathlib import Path
import tempfile

from compass.comparison import compare_rankings, comparison_markdown, main


class ComparisonTests(unittest.TestCase):
    def item(self, identifier, left, right):
        def measurement(policy, quality):
            return {"ranking": policy, "summary": [{"mode": "t1", "eligible": quality is not None,
                     "quality": {"line_recall": quality}, "cost": {"seconds": 1, "model_calls": 0, "tokens": 0}, "runs": 3}]}
        return {"instance_id": identifier, "measurements": [measurement("rrf", left),
                                                            measurement("code-aware", right)]}

    def test_only_paired_tasks_enter_means_and_repeats_do_not_add_coverage(self):
        result = compare_rankings([self.item("one", 0, .5), self.item("two", .2, .4),
                                   self.item("partial", 1, None), {"instance_id": "failed", "status": "failed"}])
        row = result["modes"]["t1"]
        self.assertEqual(row["paired_instances"], 2)
        self.assertEqual(row["excluded_instances"], ["partial", "failed"])
        self.assertAlmostEqual(row["instance_mean"]["rrf"]["line_recall"], .1)
        self.assertAlmostEqual(row["code_aware_minus_rrf"]["line_recall"], .35)
        self.assertNotIn("instance_mean", result["modes"]["t2"])

    def test_escalation_uses_same_task_baselines_and_reports_exclusions(self):
        first = self.item("complete", .1, .2)
        for measured, quality in zip(first["measurements"], (.3, .1)):
            measured["summary"].append({"mode": "t2", "eligible": True, "quality": {"line_recall": quality},
                                        "cost": {"seconds": 5, "model_calls": 2, "tokens": 100}})
        result = compare_rankings([first, self.item("t1-only", .9, .9)])
        delta = result["escalation"]["rrf"]["t2_minus_t1"]
        self.assertEqual(delta["paired_instances"], 1)
        self.assertEqual(delta["excluded_instances"], ["t1-only"])
        self.assertAlmostEqual(delta["quality_delta"]["line_recall"], .2)
        self.assertEqual(delta["quality_outcomes"]["line_recall"], {"improved": 1, "tied": 0, "regressed": 0})
        self.assertEqual(delta["cost_delta"]["model_calls"], 2)
        self.assertEqual(delta["cost_delta"]["seconds"], 4)
        self.assertAlmostEqual(result["escalation"]["code-aware"]["t2_minus_t1"]["quality_delta"]["line_recall"], -.1)
        markdown = comparison_markdown(result)
        self.assertIn("t1-only", markdown)
        self.assertIn("0.20000", markdown)
        self.assertIn("n/a", markdown)

    def test_saved_result_export_preserves_source_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "result.json"
            source.write_text(json.dumps({"all_passed": False, "instances": [self.item("one", 0, .5)]}))
            arguments = ["--result", str(source), "--output-dir", str(root / "analysis")]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(arguments), 0)
            report = json.loads((root / "analysis/comparison.json").read_text())
            self.assertFalse(report["source_all_passed"])
            self.assertEqual(len(report["source_result_sha256"]), 64)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(arguments)
