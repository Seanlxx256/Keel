import json
from pathlib import Path
import sys
import tempfile
import unittest
from keel.models import Reply
from keel.runtime import run


class ProposalValidationFeedbackTests(unittest.TestCase):
    def trial(self, calls=2, policy=False, repeat_bad=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root/'app.py').write_bytes(b'VALUE = 1\nOTHER = 3\n')
        class Model:
            def __init__(self):
                self.messages = []
            def complete_json(self, messages, **kwargs):
                self.messages.append(messages)
                bad = len(self.messages) == 1 or repeat_bad
                value = {'summary': 'update', 'edits': [{'path': 'outside.py' if policy else 'app.py',
                         'old': 'VALUE = 1\n', 'new': 'VALUE = 2' if bad else 'VALUE = 2\n'}]}
                return Reply(json.dumps(value), 10)
        model = Model()
        config = {'mode': 'proposal', 'goal': 'Update VALUE and preserve OTHER',
            'proposal': {'files': ['app.py'], 'queries': ['VALUE']},
            'verification_repair_attempts': 1, 'budget': {'max_model_calls': calls},
            'acceptance': [[sys.executable, '-B', '-c', 'import app; assert app.VALUE == 2 and app.OTHER == 3']]}
        result = run(config, root, root/'.keel/run', model=model)
        return result, model, (root/'app.py').read_bytes()

    def test_invalid_syntax_feedback_fixes_batch_against_unchanged_source(self):
        result, model, source = self.trial()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['budget']['model_calls'], 2)
        self.assertIn('Invalid patch proposal:', model.messages[1][1]['content'])
        evidence = json.loads(model.messages[1][1]['content'])['evidence']
        self.assertIn('VALUE = 1', json.dumps(evidence))
        self.assertEqual(source, b'VALUE = 2\nOTHER = 3\n')
        self.assertTrue(any(f['summary'] == 'Proposal rejected before writes' for f in result['facts']))

    def test_budget_exhaustion_does_not_write_or_reset_budget(self):
        result, model, source = self.trial(calls=1)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.messages), 1)
        self.assertEqual(source, b'VALUE = 1\nOTHER = 3\n')

    def test_policy_failure_never_retries(self):
        result, model, source = self.trial(policy=True)
        self.assertEqual(result['failure']['category'], 'policy_denied')
        self.assertEqual(len(model.messages), 1)

    def test_repeated_invalid_batch_stops_at_one_retry(self):
        result, model, source = self.trial(repeat_bad=True)
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertEqual(len(model.messages), 2)
        self.assertEqual(source, b'VALUE = 1\nOTHER = 3\n')
