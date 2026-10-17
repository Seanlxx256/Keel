import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from keel.campaign_reporting import FrozenModel, trajectory
from keel.core import ModelError


class ReportingTests(unittest.TestCase):
    def test_first_verification_pass_is_not_reported_as_recovery(self):
        self.assertEqual(trajectory({'verification_attempts': [{'verification': [{'returncode': 0}]}],
                                     'recovery': {'used_actions': 0}}, True), 'first_verification_pass')

    def test_replanning_requires_failed_round_and_plan_revision(self):
        result = {'verification_attempts': [{'verification': [{'returncode': 1}]},
                                            {'verification': [{'returncode': 0}]}],
                  'recovery_decisions': [{'action': 'replan'}], 'plans': [{'revision': 1}]}
        self.assertEqual(trajectory(result, True), 'replanning_recovery_pass')
        self.assertEqual(trajectory(result, False), 'failed')
        result['plans'] = [{'revision': 0}]
        self.assertEqual(trajectory(result, True), 'verification_recovery_pass')

    def test_frozen_provider_checks_before_paid_call(self):
        model = Mock()
        wrapped = FrozenModel(model, Mock(side_effect=ModelError('implementation changed')))
        with self.assertRaises(ModelError):
            wrapped.complete_json([])
        model.complete_json.assert_not_called()

    def test_mid_call_drift_keeps_reported_token_usage(self):
        model = Mock()
        model.complete_json.return_value = SimpleNamespace(tokens=42)
        wrapped = FrozenModel(model, Mock(side_effect=[None, ModelError('implementation changed')]))
        with self.assertRaises(ModelError) as error:
            wrapped.complete_json([])
        self.assertEqual(error.exception.tokens, 42)
