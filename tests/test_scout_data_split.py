import copy
import unittest
from keel.scout_data_split import partition_rows,reconcile_learning_rows


def fixtures():
    reviewed=[{'sample_id':str(i),'instance_id':task,'transcript':str(i),'request_line':1,'response_line':2,
        'example_sha256':str(i),'decision':'needs_semantic_review','kind':'files'} for i,task in enumerate(('a-1','a-2','b-1'))]
    audit=[dict(r,state_sha256='state-'+r['sample_id']) for r in reviewed]
    assignments={task:{'group':task[0],'partition':'training_review' if task[0]=='a' else 'transfer_review'} for task in ('a-1','a-2','b-1')}
    return reviewed,audit,[{'instance_id':'a-1','example_sha256':'0'}],assignments


class ScoutDataSplitTests(unittest.TestCase):
    def learning_inputs(self):
        reviewed,audited,_,assignment=fixtures()
        rows=partition_rows(reviewed,audited,[],assignment)
        exported={'samples':[{'sample_id':'0','example_sha256':'0'}]}
        assessment={'items':[{'sample_id':'1','example_sha256':'1','decision':'hold_symbol_relevance_review','rationale':'Needs source evidence'}]}
        return {'items':rows},{'items':reviewed},exported,assessment

    def test_reconciliation_overlays_actual_use_and_retains_transfer_and_hold(self):
        inputs=self.learning_inputs();original=copy.deepcopy(inputs)
        rows=reconcile_learning_rows(*inputs)
        self.assertEqual(inputs,original)
        self.assertEqual([r['reconciled_status'] for r in rows],['already_trained','held_by_prior_assessment','reserved_transfer_only'])
        self.assertFalse(rows[0]['previously_trained_control'])
        self.assertTrue(rows[0]['actual_previously_trained'])
        self.assertTrue(all(r['new_training_approved'] is False for r in rows))

    def test_reconciliation_does_not_reopen_excluded_examples_or_train_transfer(self):
        reservation,review,exported,assessment=self.learning_inputs()
        assessment['items'][0]['decision']='exclude_redundant_task_control'
        self.assertEqual(reconcile_learning_rows(reservation,review,exported,assessment)[1]['reconciled_status'],'excluded_by_prior_assessment')
        exported['samples'].append({'sample_id':'2','example_sha256':'2'})
        with self.assertRaisesRegex(ValueError,'outside training'):reconcile_learning_rows(reservation,review,exported,assessment)

    def test_reconciliation_rejects_stale_identity_or_duplicate_sample(self):
        reservation,review,exported,assessment=self.learning_inputs()
        assessment['items'][0]['example_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'assessment identity'):reconcile_learning_rows(reservation,review,exported,assessment)
        inputs=self.learning_inputs();inputs[0]['items'].append(inputs[0]['items'][0])
        with self.assertRaisesRegex(ValueError,'Duplicate'):reconcile_learning_rows(*inputs)

    def test_group_reservation_never_approves_or_certifies_independence(self):
        result=partition_rows(*fixtures())
        self.assertTrue(result[0]['previously_trained_control'])
        self.assertTrue(all(not r['training_approved'] and not r['independent_evaluation_eligible'] for r in result))

    def test_same_group_cannot_cross_train_transfer(self):
        rows,audit,trained,assignments=fixtures();assignments['a-2']['partition']='transfer_review'
        with self.assertRaisesRegex(ValueError,'group crosses'):partition_rows(rows,audit,trained,assignments)

    def test_used_task_cannot_be_reclassified_as_holdout(self):
        rows,audit,trained,assignments=fixtures()
        for task in ('a-1','a-2'):assignments[task]['partition']='transfer_review'
        with self.assertRaisesRegex(ValueError,'Previously trained'):partition_rows(rows,audit,trained,assignments)

    def test_identical_input_across_groups_is_rejected(self):
        rows,audit,trained,assignments=fixtures();audit[2]['state_sha256']=audit[0]['state_sha256']
        with self.assertRaisesRegex(ValueError,'input state'):partition_rows(rows,audit,trained,assignments)

    def test_missing_tasks_and_changed_review_identity_rejected(self):
        rows,audit,trained,assignments=fixtures();assignments.pop('b-1')
        with self.assertRaisesRegex(ValueError,'every reviewed task'):partition_rows(rows,audit,trained,assignments)
        rows,audit,trained,assignments=fixtures();audit[0]['example_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'identity'):partition_rows(rows,audit,trained,assignments)
