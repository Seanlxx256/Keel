import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.compare_factory_recovery import execute, prepare, summarize


class FactoryComparisonTests(unittest.TestCase):
    def prepare_plan(self, root):
        model = root/'model.json'
        model.write_text('{"name":"test"}')
        with patch('examples.compare_factory_recovery.load_factory', return_value={'candidate': {'number': 1}}), \
             patch('examples.compare_factory_recovery.inventory', return_value={'app.py': 'abc'}), \
             patch('examples.compare_factory_recovery.receipt', return_value={'frozen': 'abc'}), \
             patch('examples.compare_factory_recovery.implementation_hashes', return_value={'runtime.py': 'abc'}):
            return prepare(root, root/'comparison', [root/'factory'], model, repeats=2)

    def test_repeats_are_not_unique_tasks_and_errors_remain_denominator(self):
        planned = [{'task': 0, 'repeat': repeat, 'repair_attempts': arm}
                   for repeat in (1, 2) for arm in (0, 3)]
        records = [dict(row, status='error' if index == 0 else 'completed', passed=index == 1)
                   for index, row in enumerate(planned)]
        summary = summarize(records, planned)
        self.assertEqual(summary['unique_tasks'], 1)
        self.assertEqual(summary['arms']['0']['final_pass_rate'], 0)
        self.assertEqual(summary['arms']['3']['final_pass_rate'], 0.5)
        self.assertEqual(summary['arms']['0']['errors'], 1)
        self.assertIsNone(summarize(records[:1], planned)['arms']['0']['final_pass_rate'])

    def test_implementation_drift_stops_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.prepare_plan(root)
            with patch('examples.compare_factory_recovery.implementation_hashes', return_value={'changed': 'x'}), \
                 patch('examples.compare_factory_recovery.trial') as solve:
                with self.assertRaisesRegex(ValueError, 'Implementation changed'):
                    execute(root, root/'comparison')
                solve.assert_not_called()
            self.assertFalse((root/'comparison/execution-started.json').exists())

    def test_failed_arm_does_not_skip_remaining_planned_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.prepare_plan(root)
            calls = []
            def solve(*args, **kwargs):
                kwargs['check_frozen']()
                calls.append(kwargs['repair_attempts'])
                if len(calls) == 1:
                    raise ValueError('Environment failed')
                return {'status': 'completed', 'passed': True, 'budget': {'tokens': 10}}
            with patch('examples.compare_factory_recovery.implementation_hashes', return_value=plan['implementation']), \
                 patch('examples.compare_factory_recovery.receipt', return_value={'frozen': 'abc'}), \
                 patch('examples.compare_factory_recovery.trial', side_effect=solve):
                result = execute(root, root/'comparison')
                self.assertEqual(len(calls), 4)
                self.assertEqual(result['records'][0]['status'], 'error')
                self.assertEqual(result['summary']['recorded_runs'], 4)
                with self.assertRaises(FileExistsError):
                    execute(root, root/'comparison')

    def test_model_config_drift_rejected_before_paid_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.prepare_plan(root)
            (root/'model.json').write_text('{"name":"changed"}')
            with patch('examples.compare_factory_recovery.implementation_hashes', return_value=plan['implementation']), \
                 patch('examples.compare_factory_recovery.trial') as solve:
                with self.assertRaisesRegex(ValueError, 'Model configuration changed'):
                    execute(root, root/'comparison')
                solve.assert_not_called()
