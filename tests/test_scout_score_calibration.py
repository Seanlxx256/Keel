import unittest
from keel.scout_score_calibration import fit_threshold,threshold_metrics,grouped_crosscheck


def row(group,positive=0.95,negative=0.8):
    return {'group':group,'candidate_scores':[
        {'location':'a.py:1','candidate_id':0,'probability':positive,'teacher_member':1},
        {'location':'a.py:2','candidate_id':1,'probability':negative,'teacher_member':0}]}


class ScoreCalibrationTests(unittest.TestCase):
    def test_global_rule_reduces_training_extras_without_per_query_threshold(self):
        rows=[row(0),row(1,0.97,0.7)]
        fitted=fit_threshold(rows)
        self.assertEqual(threshold_metrics(rows,0.5)['exact_sets'],0)
        self.assertEqual(fitted['exact_sets'],2)
        self.assertGreater(fitted['threshold'],0.8)
        self.assertEqual(threshold_metrics(rows,fitted['threshold'])['exact_sets'],2)
        self.assertEqual(fit_threshold(list(reversed(rows))),fitted)

    def test_crosscheck_never_fits_held_group(self):
        rows=[row(0),row(1,0.7,0.6)]
        result=grouped_crosscheck(rows)
        for fold in result['folds']:
            expected=fit_threshold([r for r in rows if r['group']!=fold['group']])
            self.assertEqual(fold['threshold'],expected['threshold'])

    def test_calibration_does_not_force_a_correct_count_or_accept_bad_labels(self):
        rows=[row(0,0.3,0.9)]
        self.assertEqual(threshold_metrics(rows,0.95)['exact_sets'],0)
        self.assertEqual(threshold_metrics(rows,0.95)['false_negative_memberships'],1)
        for rows in ([],[row(0,float('nan'))]):
            with self.assertRaises(ValueError):fit_threshold(rows)
