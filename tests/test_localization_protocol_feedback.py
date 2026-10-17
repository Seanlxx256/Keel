import json
from pathlib import Path
import sys
import tempfile
import unittest
from keel.models import Reply
from keel.runtime import run


class LocationFeedbackTests(unittest.TestCase):
    def trial(self, correct=True, calls=4):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root/'module.py').write_bytes(b'import os\n\ndef version():\n    return 1\n')
        class Model:
            def __init__(self):
                self.messages = []
            def complete_json(self, messages, **kwargs):
                self.messages.append(messages)
                count = len(self.messages)
                value = ({'files': ['module.py']} if count == 1 else
                         {'locations': ['module.py:1', 'module.py:3']} if count == 2 or not correct else
                         {'locations': ['module.py:3']} if count == 3 else
                         {'summary': 'repair', 'edits': [{'path': 'module.py', 'old': 'return 1', 'new': 'return 2'}]})
                return Reply(json.dumps(value), 10)
        model = Model()
        result = run({'mode': 'localized-proposal', 'goal': 'Return 2', 'budget': {'max_model_calls': calls},
                      'acceptance': [[sys.executable, '-B', '-c', 'import module; assert module.version()==2']]},
                     root, root/'.keel/run', model=model)
        return result, model, (root/'module.py').read_bytes()

    def test_import_line_is_rejected_then_explicitly_corrected(self):
        result, model, source = self.trial()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['budget']['model_calls'], 4)
        feedback = json.loads(model.messages[2][1]['content'])
        self.assertEqual(feedback['invalid_locations'], ['module.py:1'])
        self.assertIn('return 2', source.decode())

    def test_repeated_invalid_locations_stop_without_edit(self):
        result, model, source = self.trial(correct=False)
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertEqual(len(model.messages), 3)
        self.assertIn(b'return 1', source)

    def test_reselection_does_not_reset_global_budget(self):
        result, model, source = self.trial(calls=2)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.messages), 2)
        self.assertIn(b'return 1', source)
