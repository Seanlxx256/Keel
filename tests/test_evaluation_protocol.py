import copy
import json
from pathlib import Path
import tempfile
import unittest

from keel.evaluation_protocol import freeze, verify, verify_results, development_status


class EvaluationProtocolTests(unittest.TestCase):
    def fixture(self, root):
        (root/'examples').mkdir()
        (root/'examples/evaluation_development_registry.json').write_text(json.dumps({
            'tasks': [{'id': 'known-1', 'repository': 'org/dev', 'pr': 1, 'reason': 'debugged'}],
            'repository_aliases': {'old/dev': 'org/dev'}}))
        (root/'keel').mkdir()
        (root/'keel/runtime.py').write_text('VERSION = 1\n')
        (root/'settings.json').write_text('{"budget":100}')
        (root/'task.json').write_text('{"acceptance":"frozen"}')
        return {'operator_declared_unseen': True, 'settings_file': 'settings.json',
            'tasks': [{'id': 'new-2', 'repository': 'org/new', 'pr': 2, 'task_file': 'task.json'}]}

    def test_known_tasks_aliases_and_entire_development_repo_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.fixture(root)
            self.assertFalse(development_status(root, 'known-1')['heldout_eligible'])
            for repo in ('org/dev', 'OLD/DEV'):
                plan['tasks'][0]['repository'] = repo
                with self.assertRaisesRegex(ValueError, 'Development'):
                    freeze(root, plan)
            plan['tasks'][0]['repository'] = 'org/new'
            plan['tasks'][0]['id'] = 'known-1'
            with self.assertRaises(ValueError):
                freeze(root, plan)

    def test_task_settings_code_and_file_set_changes_invalidate_freeze(self):
        for name in ('task.json', 'settings.json', 'keel/runtime.py', 'keel/new.py'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                frozen = freeze(root, self.fixture(root))
                self.assertTrue(verify(root, frozen)['matched'])
                (root/name).write_text('changed')
                with self.assertRaises(ValueError):
                    verify(root, frozen)

    def test_empty_duplicate_undeclared_unseen_and_escaping_files_are_rejected(self):
        for mutation in ('empty', 'duplicate', 'unseen', 'escape'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = self.fixture(root)
                if mutation == 'empty':
                    plan['tasks'] = []
                elif mutation == 'duplicate':
                    plan['tasks'].append({**plan['tasks'][0], 'id': 'alias-task'})
                elif mutation == 'unseen':
                    plan['operator_declared_unseen'] = False
                else:
                    plan['tasks'][0]['task_file'] = '../outside.json'
                with self.assertRaises(ValueError):
                    freeze(root, plan)

    def test_failure_rows_retained_retries_and_diagnostic_reports_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = freeze(root, self.fixture(root))
            results = {'protocol_sha256': frozen['protocol_sha256'],
                'settings_sha256': frozen['settings_sha256'], 'implementation_sha256': frozen['implementation_sha256'],
                'evaluation_split': 'independent', 'prepared_only': False,
                'records': [{'id': 'new-2', 'task_sha256': frozen['tasks'][0]['task_sha256'],
                    'attempt': 1, 'status': 'completed', 'executed': True, 'passed': False}]}
            self.assertEqual(verify_results(root, frozen, results)['passed'], 0)
            for mutation in ('missing', 'retry', 'diagnostic', 'fake_pass'):
                broken = copy.deepcopy(results)
                if mutation == 'missing':
                    broken['records'] = []
                elif mutation == 'retry':
                    broken['records'][0]['attempt'] = 2
                elif mutation == 'diagnostic':
                    broken['evaluation_split'] = 'development'
                else:
                    broken['records'][0].update(passed=True, executed=False)
                with self.assertRaises(ValueError):
                    verify_results(root, frozen, broken)

    def test_modified_manifest_digest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = freeze(root, self.fixture(root))
            frozen['tasks'][0]['pr'] = 99
            with self.assertRaisesRegex(ValueError, 'digest'):
                verify(root, frozen)
