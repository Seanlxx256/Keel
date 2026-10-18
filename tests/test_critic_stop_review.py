import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from keel.core import Budget, BudgetExceeded, Limits
from keel.models import Reply
from keel.recovery import RecoveryController


class CriticStopReviewTests(unittest.TestCase):
    def decide(self, actions, *, group='PASS_TO_PASS', changed=True, max_calls=5):
        ws = SimpleNamespace(budget=Budget(Limits(max_model_calls=max_calls)),
                             ledger=Mock(), trace=Mock())
        ws.ledger.add.return_value = 1
        controller = RecoveryController({'max_actions': 4}, ws)
        calls = []
        def complete(messages, **kwargs):
            calls.append(messages)
            return Reply(json.dumps({'action': actions[len(calls)-1], 'reason': 'Inspect or identify a blocker',
                'hypothesis': 'Cause unverified', 'evidence': 'Observed test failure and diff',
                'next_check': 'Inspect source', 'previous_attempt_assessment': 'Acceptance still fails'}), 10)
        model = SimpleNamespace(complete_json=complete)
        verification = [{'returncode': 1, 'stdout': json.dumps({'failure_kind': 'test_failure',
            'failed_tests': [{'group': group, 'test': 'tests/test_value.py::test_other_input'}]})}]
        changes = {'changes': [{'path': 'library.py', 'diff': '-old\n+new'}]} if changed else {}
        return controller, ws, calls, lambda: controller.decide(model, 'Fix reported example', [], verification,
                                                               {'max_context_bytes': 24000}, changes=changes)

    def test_uncertain_preservation_failure_gets_one_review_and_can_replan(self):
        controller, ws, calls, invoke = self.decide(['stop', 'replan'])
        self.assertEqual(invoke()['action'], 'replan')
        self.assertEqual(ws.budget.model_calls, 2)
        contract = json.loads(calls[0][1]['content'])['acceptance_contract']
        self.assertEqual(len(contract['observed_pass_to_pass_failures']), 1)
        self.assertIn('unrelated', calls[1][1]['content'])
        self.assertEqual([row['action'] for row in controller.decisions], ['stop', 'replan'])

    def test_genuine_stop_is_not_overridden_or_reviewed_forever(self):
        _, ws, _, invoke = self.decide(['stop', 'stop'])
        self.assertEqual(invoke()['action'], 'stop')
        self.assertEqual(ws.budget.model_calls, 2)

    def test_no_current_diff_does_not_trigger_review(self):
        _, ws, _, invoke = self.decide(['stop'], changed=False)
        self.assertEqual(invoke()['action'], 'stop')
        self.assertEqual(ws.budget.model_calls, 1)

    def test_stop_review_shares_global_budget(self):
        _, ws, _, invoke = self.decide(['stop'], max_calls=1)
        with self.assertRaises(BudgetExceeded):
            invoke()
        self.assertEqual(ws.budget.model_calls, 1)
