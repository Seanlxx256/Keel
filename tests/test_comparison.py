import unittest

from compass.comparison import compare_rankings


class ComparisonTests(unittest.TestCase):
    def item(self, identifier, left, right):
        def measurement(policy, quality):
            return {"ranking": policy, "summary": [{"mode": "t1", "eligible": quality is not None,
                     "quality": {"line_recall": quality}, "runs": 3}]}
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
