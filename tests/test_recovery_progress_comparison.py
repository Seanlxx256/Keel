import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.run_recovery_progress_comparison import LIMITS, execute_pair, validate_host, validate_trial, verify_completed
from examples.run_swebench_task import trial_budget
from keel.core import ModelError


class RecoveryProgressComparisonTests(unittest.TestCase):
    def test_selected_host_requires_mcp_only_when_profile_is_enabled(self):
        with patch('examples.run_recovery_progress_comparison.find_spec', return_value=None):
            validate_host({'mcp_config': None})
            with self.assertRaisesRegex(ValueError, 'host Python lacks'):
                validate_host({'mcp_config': 'profile.json'})

    def fixture(self, root):
        output = root/'pair'; output.mkdir()
        (output/'plan.json').write_text('{}')
        model = root/'model.json'; model.write_text('{}')
        paths = {key: root/key for key in ('task', 'reference_grade', 'harness_python', 'resume_snapshot', 'saved_repo')}
        paths.update(model_config=model, mcp_config=None)
        plan = {'implementation': {}, 'continuation': {}, 'limits_per_arm': LIMITS,
                'scope': 'development', 'cost_boundary': 'agent only',
                'arms': [{'name': 'baseline', 'recovery_progress': False},
                         {'name': 'progress', 'recovery_progress': True}]}
        return output, plan, paths

    def fake_execute(self, plan):
        def execute(root, task, reference, model, harness, output, **kwargs):
            output.mkdir(); (output/'final-grade').mkdir(); (output/'run').mkdir()
            enabled = kwargs['recovery_progress']
            self.assertFalse(kwargs['diagnostic_inspection'])
            self.assertEqual(kwargs['budget_limits'], LIMITS)
            row = {'status': 'completed', 'official_resolved': False, 'runtime_status': 'failed',
                   'implementation': plan['implementation'], 'continuation': plan['continuation'],
                   'recovery_progress': enabled, 'diagnostic_inspection': False,
                   'limits': LIMITS, 'budget': {'limits': LIMITS, 'model_calls': 6, 'tokens': 1000},
                   'failure': {'category': 'verification_failed'}, 'verification_rounds': 2}
            (output/'trial.json').write_text(json.dumps(row))
            (output/'final-grade'/'grading.json').write_text(json.dumps({
                'status': 'graded', 'official_resolved': False, 'infra_failure': None}))
            (output/'run'/'trace.jsonl').write_text(json.dumps({
                'role': 'critic', 'event': 'llm_call_started', 'recovery_progress_context': enabled})+'\n')
            return row
        return execute

    def test_equal_bounded_arms_resume_without_new_model_or_agent_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output, plan, paths = self.fixture(root)
            with patch('examples.run_recovery_progress_comparison.validate_plan', return_value=(plan, paths)), \
                 patch('examples.run_recovery_progress_comparison.from_config') as model, \
                 patch('examples.run_recovery_progress_comparison.execute', side_effect=self.fake_execute(plan)) as run:
                result = execute_pair(root, output)
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(result['outcome'], 'both_failed_no_efficacy_winner')
                self.assertEqual(result['treatment_exposure'], 'feedback_dispatched')
                self.assertEqual(run.call_count, 2)
                self.assertEqual(model.call_count, 2)
                self.assertEqual(execute_pair(root, output), result)
                self.assertEqual(run.call_count, 2)
                self.assertEqual(model.call_count, 2)
            (output/'baseline'/'trial.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'receipt mismatch'):
                verify_completed(output/'baseline', plan['arms'][0], plan)

    def test_model_error_stops_pair_and_preserves_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output, plan, paths = self.fixture(root)
            def fail(*args, **kwargs):
                (output/'baseline').mkdir()
                raise ModelError('transport unavailable')
            with patch('examples.run_recovery_progress_comparison.validate_plan', return_value=(plan, paths)), \
                 patch('examples.run_recovery_progress_comparison.from_config'), \
                 patch('examples.run_recovery_progress_comparison.execute', side_effect=fail) as run:
                with self.assertRaises(ModelError):
                    execute_pair(root, output)
                self.assertEqual(run.call_count, 1)
                self.assertFalse((output/'progress').exists())
                with self.assertRaisesRegex(ValueError, 'no completed receipt'):
                    execute_pair(root, output)
                self.assertEqual(run.call_count, 1)
            self.assertEqual(json.loads((output/'comparison.json').read_text())['status'], 'incomplete')

    def test_budget_can_only_shrink_and_bad_trials_cannot_be_reused(self):
        self.assertEqual(trial_budget(LIMITS), LIMITS)
        for invalid in ({'max_model_calls': 31}, {'max_tokens': True}, {'max_wallclock': 0}, {'unknown': 1}):
            with self.assertRaises(ValueError):
                trial_budget(invalid)
        plan = {'implementation': {}, 'continuation': {}, 'limits_per_arm': LIMITS}
        arm = {'recovery_progress': True}
        for row in ({}, {'status': 'completed', 'official_resolved': False, 'recovery_progress': False}):
            with self.assertRaises(ValueError):
                validate_trial(row, arm, plan)
