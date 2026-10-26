import unittest
from keel.scout_transfer_data import check_transfer_scope


class ScoutTransferDataTests(unittest.TestCase):
    def fixture(self):
        case={'sample_id':'x','instance_id':'new-task','decision':'approved_development_transfer',
            'use':'evaluation_only','independent_evaluation_eligible':False,'raw_target_modified':False}
        reserved={'items':[{'sample_id':'x','instance_id':'new-task','partition':'transfer_review',
            'previously_trained_control':False,'group':'new'},
            {'sample_id':'t','instance_id':'old-task','group':'old'}]}
        return case,reserved,{'old-task'}

    def test_evaluation_only_scope_accepted_without_independence_upgrade(self):
        check_transfer_scope(*self.fixture())

    def test_trained_task_or_group_rejected(self):
        case,reserved,trained=self.fixture();trained.add('new-task')
        with self.assertRaisesRegex(ValueError,'already present'):check_transfer_scope(case,reserved,trained)
        case,reserved,trained=self.fixture();reserved['items'][0]['group']='old'
        with self.assertRaisesRegex(ValueError,'group overlaps'):check_transfer_scope(case,reserved,trained)

    def test_training_permission_or_independence_upgrade_rejected(self):
        for field,value in [('use','training'),('independent_evaluation_eligible',True),('raw_target_modified',True)]:
            case,reserved,trained=self.fixture();case[field]=value
            with self.assertRaisesRegex(ValueError,'scope'):check_transfer_scope(case,reserved,trained)

    def test_task_name_cannot_be_changed_to_bypass_reservation(self):
        case,reserved,trained=self.fixture();case['instance_id']='unrelated'
        with self.assertRaisesRegex(ValueError,'sample/task'):check_transfer_scope(case,reserved,trained)
