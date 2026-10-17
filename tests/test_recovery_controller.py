import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from keel.core import BudgetExceeded, InputCapacityExceeded, ModelError, PolicyDenied
from keel.models import Reply
from keel.runtime import run


class RecoveryTests(unittest.TestCase):
    def workspace(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root/'library.py').write_text('def value():\n    return 1\n', encoding='utf-8')
        return root

    def config(self, actions=4):
        return {'mode': 'localized-proposal', 'goal': 'Return 3',
            'recovery': {'max_actions': actions, 'repeat_limit': 1},
            'budget': {'max_model_calls': 10},
            'acceptance': [[sys.executable, '-B', '-c', 'import library; assert library.value() == 3']]}

    def model(self, responses):
        class Model:
            def __init__(self):
                self.calls = []
            def complete_json(self, messages, **kwargs):
                self.calls.append(messages)
                value = responses[len(self.calls)-1]
                if isinstance(value, Exception):
                    raise value
                return Reply(json.dumps(value), 10)
        return Model()

    def edit(self, old, new):
        return {'summary': 'updated', 'edits': [{'path': 'library.py', 'old': old, 'new': new}]}

    def test_format_then_verification_failure_recover_in_one_shared_controller(self):
        root = self.workspace()
        model = self.model([{'files': ['library.py']}, {'locations': ['library.py:1']},
            {'wrong': 'shape'}, self.edit('return 1', 'return 2'), self.edit('return 2', 'return 3')])
        result = run(self.config(), root, root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['budget']['model_calls'], 5)
        self.assertEqual([a['action'] for a in result['recovery']['actions']], ['correct_proposal', 'repair_verification'])
        self.assertEqual(len(result['verification_attempts']), 2)
        self.assertIn('AssertionError', model.calls[-1][1]['content'])

    def test_global_model_budget_never_resets_on_recovery(self):
        root = self.workspace()
        config = self.config()
        config['budget']['max_model_calls'] = 3
        model = self.model([{'files': ['library.py']}, {'locations': ['library.py:1']}, {'wrong': 'shape'}])
        result = run(config, root, root/'.keel/run', model=model)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.calls), 3)
        self.assertIn('return 1', (root/'library.py').read_text())

    def test_transport_and_permission_errors_do_not_retry(self):
        for error in (ModelError('HTTP 401'), PolicyDenied('blocked')):
            with self.subTest(error=type(error).__name__):
                root = self.workspace()
                model = self.model([{'files': ['library.py']}, {'locations': ['library.py:1']}, error])
                result = run(self.config(), root, root/'.keel/run', model=model)
                self.assertEqual(result['recovery']['used_actions'], 0)
                self.assertEqual(len(model.calls), 3)

    def test_input_capacity_triggers_current_scope_reselection(self):
        from keel.proposals import _propose_once
        root = self.workspace()
        model = self.model([{'files': ['library.py']}, {'locations': ['library.py:1']},
                            {'locations': ['library.py:1']}, self.edit('return 1', 'return 3')])
        calls = 0
        def oversized_first(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise InputCapacityExceeded('request too large')
            return _propose_once(*args, **kwargs)
        with patch('keel.proposals._propose_once', side_effect=oversized_first):
            result = run(self.config(), root, root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['recovery']['actions'][0]['action'], 'reselect_evidence')
        self.assertEqual(json.loads(model.calls[2][1]['content'])['structure'][0]['path'], 'library.py')

    def test_repeated_identical_failure_stops_without_write(self):
        root = self.workspace()
        model = self.model([{'files': ['library.py']}, {'locations': ['library.py:1']},
                            {'wrong': 'shape'}, {'wrong': 'shape'}])
        result = run(self.config(), root, root/'.keel/run', model=model)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.calls), 4)
        self.assertEqual(result['recovery']['used_actions'], 1)
        self.assertIn('return 1', (root/'library.py').read_text())

    def test_recovery_configuration_rejected_before_artifacts(self):
        root = self.workspace()
        config = self.config(actions=True)
        with self.assertRaises(ValueError):
            run(config, root, root/'output')
        self.assertFalse((root/'output').exists())

    def test_junit_repair_uses_fresh_report_directory_each_round(self):
        root = self.workspace()
        model = self.model([{'files': ['library.py']}, {'locations': ['library.py:1']},
                            self.edit('return 1', 'return 2'), self.edit('return 2', 'return 3')])
        script = ('import library,pathlib,sys; ok=library.value()==3; '
                  'pathlib.Path(sys.argv[1]).write_text(\'<testsuite><testcase name="value">\'+ '
                  '(\'\' if ok else \'<failure/>\')+\'</testcase></testsuite>\'); sys.exit(0 if ok else 1)')
        config = self.config()
        config['acceptance'] = [{'command': [sys.executable, '-B', '-c', script, '{junit}'], 'junit': True}]
        result = run(config, root, root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed')
        reports = [round['verification'][0]['report_path'] for round in result['verification_attempts']]
        self.assertEqual(len(set(reports)), 2)
        self.assertTrue(all(Path(report).is_file() for report in reports))

    def test_repair_does_not_ignore_removed_test_identities(self):
        root = self.workspace()
        model = self.model([{'files': ['library.py']}, {'locations': ['library.py:1']},
                            self.edit('return 1', 'return 2')])
        config = self.config()
        config['acceptance'] = [{'command': [sys.executable, '-c', 'pass', '{junit}'], 'junit': True}]
        baseline = {'returncode': 1, 'timeout': False, 'junit_required': True,
                    'metadata': {'collected': 2, 'skipped': 0, 'failures': 1, 'errors': 0,
                                 'test_ids': {'one': 1, 'two': 1}}}
        removed = {'returncode': 1, 'timeout': False, 'junit_required': True,
                   'metadata': {'collected': 1, 'skipped': 0, 'failures': 1, 'errors': 0,
                                'test_ids': {'one': 1}}}
        with patch('keel.workspace.Workspace.verify', side_effect=[[baseline], [removed]]):
            result = run(config, root, root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('test_cases_removed', result['failure']['message'])
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(result['recovery']['used_actions'], 0)

    def test_tool_loop_agent_observes_verification_and_edits_again(self):
        root = self.workspace()
        replies = [
            {'final': {'summary': 'value needs updating', 'files': ['library.py']}},
            {'final': [{'id': 'update', 'description': 'Update value', 'files': ['library.py']}]},
            {'tool': 'read_file', 'arguments': {'path': 'library.py'}},
            {'tool': 'replace', 'arguments': {'path': 'library.py', 'old': 'return 1', 'new': 'return 2'}},
            {'final': 'Updated value'},
            {'tool': 'read_file', 'arguments': {'path': 'library.py'}},
            {'tool': 'replace', 'arguments': {'path': 'library.py', 'old': 'return 2', 'new': 'return 3'}},
            {'final': 'Corrected value'}]
        model = self.model(replies)
        config = self.config()
        config.update(mode='agent', agent={'max_steps': 4, 'require_change': True})
        result = run(config, root, root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['budget']['model_calls'], 8)
        self.assertEqual(result['recovery']['used_actions'], 1)
        self.assertIn('AssertionError', str(model.calls[5]))
        self.assertEqual(len(result['verification_attempts']), 2)
