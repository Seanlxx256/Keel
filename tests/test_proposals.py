import json
from pathlib import Path
import sys
import tempfile
import unittest

from keel.models import Reply
from keel.runtime import run


class ProposalTests(unittest.TestCase):
    def test_correct_change_with_matching_preservation_entry_is_accepted(self):
        (self.root/'app.py').write_bytes(b'VERSION = 1\n\ndef greeting(name):\n    return "Hello, " + name\n')
        keep = 'def greeting(name):\n    return "Hello, " + name\n'
        result, _ = self.execute([
            {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'},
            {'path': 'app.py', 'old': keep, 'new': keep}])
        self.assertEqual(result['status'], 'passed')
        normalization = [fact for fact in result['facts'] if fact['summary'] == 'Validated proposal normalization']
        self.assertEqual(len(normalization), 1)
        self.assertIn('return "Hello, " + name', (self.root/'app.py').read_text())

    def test_noop_only_proposal_is_not_success(self):
        result, _ = self.execute([{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 1'}])
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertIn('no effective changes', result['failure']['message'])
        self.assertEqual(result['verification'], [])

    def test_fabricated_preservation_entry_still_invalidates_batch(self):
        result, _ = self.execute([
            {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'},
            {'path': 'app.py', 'old': 'not in source', 'new': 'not in source'}])
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertIn('matched 0 occurrences', result['failure']['message'])
        self.assertEqual((self.root/'app.py').read_text(), 'VERSION = 1\n')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root/'app.py').write_text('VERSION = 1\n')
        self.config = {'mode': 'proposal', 'goal': 'Upgrade VERSION to 2 in app.py',
            'proposal': {'files': ['app.py'], 'queries': ['VERSION']},
            'agent': {'max_context_bytes': 12000}, 'budget': {'max_tokens': 100000},
            'acceptance': [[sys.executable, '-c', 'import app; assert app.VERSION == 2']]}

    def execute(self, edits, callback=None):
        class Model:
            calls = 0
            def complete_json(inner, messages, **kwargs):
                inner.calls += 1
                self.assertIn('VERSION = 1', json.dumps(messages))
                if callback:
                    callback()
                return Reply(json.dumps({'summary': 'Proposed upgrade', 'edits': edits}), 25)
        model = Model()
        result = run(self.config, self.root, self.root/'.keel/run', model=model)
        return result, model

    def test_one_model_proposal_executes_all_roles_and_independent_acceptance(self):
        result, model = self.execute([{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['mode'], 'proposal')
        self.assertEqual(model.calls, 1)
        self.assertEqual(result['budget']['model_calls'], 1)
        self.assertEqual(result['audit']['changed_files'], ['app.py'])
        self.assertEqual(result['verification'][0]['returncode'], 0)

    def test_entire_sequence_is_checked_before_first_write(self):
        result, model = self.execute([
            {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'},
            {'path': 'app.py', 'old': 'not present', 'new': 'anything'}])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertEqual((self.root/'app.py').read_text(), 'VERSION = 1\n')

    def test_undeclared_target_is_denied(self):
        (self.root/'other.py').write_text('VERSION = 1\n')
        result, _ = self.execute([{'path': 'other.py', 'old': '1', 'new': '2'}])
        self.assertEqual(result['failure']['category'], 'policy_denied')
        self.assertEqual((self.root/'other.py').read_text(), 'VERSION = 1\n')

    def test_source_change_during_generation_is_denied(self):
        result, _ = self.execute([{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}],
            callback=lambda: (self.root/'app.py').write_text('VERSION = 3\n'))
        self.assertEqual(result['failure']['category'], 'policy_denied')
        self.assertEqual((self.root/'app.py').read_text(), 'VERSION = 3\n')

    def test_valid_syntax_wrong_answer_still_fails_verifier(self):
        result, _ = self.execute([{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 3'}])
        self.assertEqual(result['failure']['category'], 'verification_failed')

    def test_input_limit_stops_before_model(self):
        self.config['agent']['max_context_bytes'] = 1
        result, model = self.execute([{'path': 'app.py', 'old': '1', 'new': '2'}])
        self.assertEqual(model.calls, 0)
        self.assertEqual(result['budget']['model_calls'], 0)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')

    def test_invalid_python_is_rejected_before_write(self):
        result, _ = self.execute([{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = ('}])
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertEqual((self.root/'app.py').read_text(), 'VERSION = 1\n')

    def test_protected_source_is_rejected_before_model(self):
        (self.root/'tests').mkdir()
        (self.root/'tests/test_app.py').write_text('assert True\n')
        self.config['proposal']['files'] = ['tests/test_app.py']
        result, model = self.execute([])
        self.assertEqual(result['failure']['category'], 'policy_denied')
        self.assertEqual(model.calls, 0)
