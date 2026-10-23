import unittest

from keel.diagnostic_closure import terminal_decision


class ClosureTests(unittest.TestCase):
    def decide(self, row, action='blocked', ids=None):
        return terminal_decision({'action':action,'evidence_ids':ids or ['e1']},
                                 [row],required=True)['state']

    def test_history_cannot_certify_blocker_or_answer(self):
        row={'evidence_id':'e1','kind':'execution','historical':True,
             'execution':{'returncode':1}}
        self.assertEqual(self.decide(row),'acquire')
        self.assertEqual(self.decide(row,'answer'),'acquire')

    def test_child_error_is_not_executor_obstacle(self):
        row={'evidence_id':'e1','kind':'execution','execution':{'returncode':0},
             'probe':{'returncode':1},'outcome':'script_failed'}
        self.assertEqual(self.decide(row),'acquire')

    def test_executor_timeout_and_error_support_blocker(self):
        for result in ({'returncode':1},{'timeout':True}):
            self.assertEqual(self.decide({'evidence_id':'e1','kind':'execution',
                                         'execution':result}),'blocked_verified')

    def test_fabricated_citation_does_not_certify_blocker(self):
        self.assertEqual(self.decide({'evidence_id':'e1','kind':'execution',
                                     'execution':{'returncode':1}},ids=['other']),'acquire')

    def test_success_is_diagnosis_only(self):
        self.assertEqual(self.decide({'evidence_id':'e1','kind':'execution',
                                     'execution':{'returncode':0}},'answer'),'diagnosis_ready')
