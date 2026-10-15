import copy
import json
import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from examples.reproduce_starlette_1936 import PACKAGES, assess
from examples.run_starlette_upgrade_task import BASE, GOLD, inventory, task_config, verify_range


def executions():
    versions = dict(package.split('==') for package in PACKAGES)
    base = [{'case': case, 'passed': False, 'type': 'AttributeError',
             'message': "module 'anyio' has no attribute 'start_blocking_portal'"}
            for case in ['request', 'lifespan']]
    gold = [{'case': case, 'passed': True} for case in ['request', 'lifespan']]
    return {phase: {'backend': 'docker', 'returncode': code, 'timeout': False,
                    'stdout': json.dumps({'records': rows, 'versions': versions})}
            for phase, rows, code in [('base', base, 1), ('gold', gold, 0)]}


class ReproductionTests(unittest.TestCase):
    def test_export_config_has_no_gold_revision_or_replacement_answer(self):
        config = task_config('sha256:' + 'a' * 64)
        encoded = json.dumps(config)
        self.assertNotIn(GOLD, encoded)
        self.assertNotIn('anyio.from_thread', encoded)
        self.assertNotIn('edits', config)
        self.assertEqual(config['mode'], 'agent')
        self.assertEqual(config['execution']['backend'], 'docker')
        self.assertEqual(config['model']['num_gpu'], 0)

    def test_range_checks_commit_header_and_exact_changed_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            base, gold = Path(directory)/'base', Path(directory)/'gold'
            for root in (base, gold):
                (root/'starlette').mkdir(parents=True)
                (root/'starlette/testclient.py').write_text('base')
                (root/'.git').mkdir()
                (root/'.git/config').write_text('not exported')
            (gold/'starlette/testclient.py').write_text('gold')
            result = SimpleNamespace(stdout='tree ' + 'a'*40 + '\nparent ' + BASE + '\n\nmessage\n')
            with patch('examples.run_starlette_upgrade_task.check_snapshot'), patch(
                    'examples.run_starlette_upgrade_task.subprocess.run', return_value=result):
                self.assertEqual(verify_range(base, gold)['changed_files'], ['starlette/testclient.py'])
                self.assertNotIn('.git/config', inventory(base))
                (gold/'extra.py').write_text('unexpected')
                with self.assertRaisesRegex(ValueError, 'changed|changes'):
                    verify_range(base, gold)
                result.stdout = 'parent ' + 'c'*40 + '\n\nmessage'
                with self.assertRaisesRegex(ValueError, 'first parent'):
                    verify_range(base, gold)

    def test_requires_specific_base_failure_and_gold_pass_in_identical_environment(self):
        self.assertTrue(assess(executions()))
        for phase, field, value in [('base', 'returncode', 0), ('gold', 'returncode', 1),
                                    ('gold', 'timeout', True), ('base', 'backend', 'local'),
                                    ('base', 'stdout', 'installation failed')]:
            with self.subTest(phase=phase, field=field):
                runs = executions()
                runs[phase][field] = value
                self.assertFalse(assess(runs))

    def test_missing_cases_wrong_versions_and_unrelated_failures_are_not_success(self):
        for change in ['missing_case', 'wrong_version', 'unrelated_failure', 'partial_gold']:
            runs = copy.deepcopy(executions())
            phase = 'gold' if change == 'partial_gold' else 'base'
            data = json.loads(runs[phase]['stdout'])
            if change == 'missing_case':
                data['records'].pop()
            elif change == 'wrong_version':
                data['versions']['anyio'] = '3.0.0'
            elif change == 'unrelated_failure':
                data['records'][0]['message'] = 'unrelated attribute missing'
            else:
                data['records'][0]['passed'] = False
            runs[phase]['stdout'] = json.dumps(data)
            with self.subTest(change=change):
                self.assertFalse(assess(runs))
