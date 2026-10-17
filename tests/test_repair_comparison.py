import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.run_repair_comparison import prepare, execute, case_records, pair_key


class RepairComparisonTests(unittest.TestCase):
    def test_preparation_freezes_pairs_without_provider_and_blocks_changed_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root/'model.json'
            model.write_text(json.dumps({'provider': 'openai-compatible', 'name': 'fixture',
                                         'base_url': 'https://example.invalid/v1'}))
            spec = {'id': 'fixture', 'files': {'module.py': b'def f():\n    return 1\n'},
                    'target': 'module.py', 'goal': 'Return 2', 'acceptance': 'assert False',
                    'reference_execution': {'stdout': json.dumps({'records': [{'case': 'one', 'passed': True}]})}}
            with patch('examples.run_repair_comparison.real_task', return_value=(spec, 'sha256:'+'a'*64, 'provenance')), \
                 patch('examples.run_repair_comparison.from_config') as provider:
                plan = prepare(root, root/'out', model, [('fixture', root)])
            provider.assert_called_once()
            self.assertEqual(len(plan['rows']), 2)
            self.assertEqual(plan['heldout_tasks'], 0)
            a, b = plan['rows']
            self.assertEqual(pair_key(a['config']), pair_key(b['config']))
            self.assertEqual({a['repair_attempts'], b['repair_attempts']}, {0, 2})
            self.assertEqual(a['source'], b['source'])
            with patch('examples.run_repair_comparison.real_task', return_value=(spec, 'sha256:'+'a'*64, 'provenance')), \
                 patch('examples.run_repair_comparison.from_config'):
                single = prepare(root, root/'single', model, [('fixture', root)], arms=(2,))
            self.assertEqual(len(single['rows']), 1)
            self.assertEqual(single['rows'][0]['repair_attempts'], 2)
            self.assertEqual(single['experiment_kind'], 'single-arm diagnostic')
            (root/'out'/b['directory']/'repo/module.py').write_text('changed')
            with patch('examples.run_repair_comparison.run') as runner:
                with self.assertRaisesRegex(ValueError, 'Source/path mismatch'):
                    execute(root, root/'out')
                runner.assert_not_called()
            self.assertFalse((root/'out/execution-started.json').exists())

    def test_execution_retains_failed_arm_and_continues_other_arm(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root/'model.json'
            model.write_text('{}')
            spec = {'id': 'fixture', 'files': {'module.py': b'def f():\n    return 1\n'},
                    'target': 'module.py', 'goal': 'Return 2', 'acceptance': 'assert False',
                    'reference_execution': {'stdout': json.dumps({'records': [{'case': 'one', 'passed': True}]})}}
            with patch('examples.run_repair_comparison.real_task', return_value=(spec, 'sha256:'+'a'*64, 'p')), patch('examples.run_repair_comparison.from_config'):
                prepare(root, root/'out', model, [('fixture', root)])
            baseline = {'backend': 'docker', 'timeout': False, 'returncode': 1,
                        'stdout': json.dumps({'records': [{'case': 'one', 'passed': False}]})}
            count = []
            def runtime(config, repo, output):
                count.append(1)
                if len(count) == 1:
                    raise RuntimeError('fixture failure')
                (repo/'module.py').write_text('def f():\n    return 2\n')
                accepted = {**baseline, 'returncode': 0, 'stdout': spec['reference_execution']['stdout']}
                return {'status': 'passed', 'verification': [accepted], 'budget': {'model_calls': 1}, 'failure': None}
            with patch('examples.run_repair_comparison.CommandRunner') as command, patch('examples.run_repair_comparison.run', side_effect=runtime):
                command.return_value.run.return_value = baseline
                report = execute(root, root/'out')
            self.assertEqual([r['passed'] for r in report['records']], [False, True])
            self.assertEqual(report['records'][0]['status'], 'runtime_error')
            self.assertTrue((root/'out/results.json').exists())

    def test_duplicate_cases_are_rejected(self):
        with self.assertRaises(ValueError):
            case_records({'stdout': json.dumps({'records': [{'case': 'one', 'passed': True}]*2})})

    def test_pair_key_preserves_every_other_configuration(self):
        self.assertEqual(pair_key({'verification_repair_attempts': 0, 'budget': 3}),
                         pair_key({'verification_repair_attempts': 2, 'budget': 3}))
        self.assertNotEqual(pair_key({'budget': 3}), pair_key({'budget': 4}))
