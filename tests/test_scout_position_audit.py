import copy
import unittest
from keel.scout_position_audit import audit_pair


def report():
    return dict(status='completed', training_receipt_sha256='train', dataset_sha256='data',
        checkpoint_step=168, selection_policy={'threshold': .5, 'max_items': 8},
        rows=[dict(sample=0, candidate_scores=[
            dict(location='a.py:1', token_position=10, probability=.2, teacher_member=0),
            dict(location='a.py:2', token_position=20, probability=.8, teacher_member=1)])])


class PositionAuditTests(unittest.TestCase):
    def test_representation_drift_cannot_be_paired(self):
        before=report();after=report();after['score_representation']='id_free_after'
        with self.assertRaisesRegex(ValueError,'representation differs'):audit_pair(before,after)

    def test_pairs_by_location_not_list_order_or_id(self):
        a=report(); b=copy.deepcopy(a)
        b['rows'][0]['candidate_scores'].reverse()
        b['rows'][0]['candidate_scores'][0].update(token_position=10, probability=.3)
        b['rows'][0]['candidate_scores'][1].update(token_position=20, probability=.7)
        result=audit_pair(a,b)
        self.assertEqual(result['moved_candidates'],2)
        self.assertEqual(result['threshold_crossings'],2)
        self.assertAlmostEqual(result['position_score_delta_correlation'],1.)

    def test_identical_scores_have_undefined_not_zero_correlation(self):
        self.assertIsNone(audit_pair(report(),report())['position_score_delta_correlation'])

    def test_rejects_incomplete_or_mismatched_evidence(self):
        for change in ('status','checkpoint_step','label','coverage'):
            b=report()
            if change=='status': b['status']='running'
            elif change=='checkpoint_step': b['checkpoint_step']=1
            elif change=='label': b['rows'][0]['candidate_scores'][0]['teacher_member']=1
            else: b['rows'][0]['candidate_scores'].pop()
            with self.subTest(change=change), self.assertRaises(ValueError): audit_pair(report(),b)
