import json
from pathlib import Path
import sys
import tempfile
import unittest

from keel.models import Reply
from keel.runtime import run


class VerificationRepairTests(unittest.TestCase):
    def trial(self, rounds=1, calls=4):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root/'module.py').write_text('def version():\n    return 1\n')
        config = {'mode': 'localized-proposal', 'goal': 'Return 3',
            'verification_repair_attempts': rounds,
            'budget': {'max_model_calls': calls},
            'acceptance': [[sys.executable, '-B', '-c', 'import module; assert module.version() == 3']]}
        class Model:
            def __init__(self):
                self.messages = []
            def complete_json(self, messages, **kwargs):
                self.messages.append(messages)
                index = len(self.messages)
                value = ({'files': ['module.py']} if index == 1 else
                         {'locations': ['module.py:1']} if index == 2 else
                         {'summary': 'repair', 'edits': [{'path': 'module.py',
                          'old': 'return 1' if index == 3 else 'return 2',
                          'new': 'return 2' if index == 3 else 'return 3'}]})
                return Reply(json.dumps(value), 10)
        model = Model()
        return run(config, root, root/'.keel/run', model=model), model

    def test_failure_feedback_repairs_current_source_with_shared_budget(self):
        result, model = self.trial()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['budget']['model_calls'], 4)
        self.assertEqual(len(result['verification_attempts']), 2)
        self.assertNotEqual(result['verification_attempts'][0]['verification'][0]['returncode'], 0)
        self.assertIn('return 2', model.messages[-1][1]['content'])
        self.assertIn('AssertionError', model.messages[-1][1]['content'])
        self.assertTrue(any(f['kind'] == 'failed_attempt' for f in result['facts']))

    def test_repair_reacquires_omitted_file_before_second_patch(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'first.py').write_bytes(b'def first():\n    return 1\n')
            (root/'second.py').write_bytes(b'def second():\n    return 2\n')
            replies = [{'files': ['first.py', 'second.py']},
                       {'locations': ['first.py:1', 'second.py:1']},
                       {'edits': [{'path': 'first.py', 'old': 'return 1', 'new': 'return 2'}], 'summary': 'initial'},
                       {'locations': ['second.py:1']},
                       {'edits': [{'path': 'second.py', 'old': 'return 2', 'new': 'return 3'}], 'summary': 'repair'}]
            class Model:
                def __init__(self):
                    self.messages = []
                def complete_json(self, messages, **kwargs):
                    self.messages.append(messages)
                    return Reply(json.dumps(replies[len(self.messages)-1]), 10)
            failed = {'returncode': 1, 'stdout': json.dumps({'records': [{'case': 'one', 'passed': False,
                'message': 'observed failure', 'traceback': 'File "/workspace/first.py", line 2'}]}), 'stderr': ''}
            passed = {'returncode': 0, 'stdout': '', 'stderr': ''}
            model = Model()
            config = {'mode': 'localized-proposal', 'goal': 'repair', 'verification_repair_attempts': 1,
                      'budget': {'max_model_calls': 5}, 'acceptance': [[sys.executable, '-c', 'pass']]}
            with patch('keel.workspace.Workspace.verify', side_effect=[[failed], [passed]]):
                result = run(config, root, root/'.keel/run', model=model)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['budget']['model_calls'], 5)
            request = json.loads(model.messages[-1][1]['content'])
            self.assertEqual(request['allowed_files'], ['second.py'])
            self.assertIn('return 3', (root/'second.py').read_text())

    def test_default_zero_rounds_keeps_first_failure(self):
        result, model = self.trial(rounds=0)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(model.messages), 3)
        self.assertEqual(len(result['verification_attempts']), 1)

    def test_retry_cannot_reset_global_model_budget(self):
        result, model = self.trial(calls=3)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.messages), 3)
        self.assertEqual(len(result['verification_attempts']), 1)
