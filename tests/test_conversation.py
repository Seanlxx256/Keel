import json
from pathlib import Path
import sys
import tempfile
import unittest

from keel.conversation import BoundedConversation, size
from keel.core import BudgetExceeded
from keel.models import Reply
from keel.runtime import run


class ConversationTests(unittest.TestCase):
    def test_runtime_oversize_stops_before_charging_or_sending_model_request(self):
        class Model:
            def complete(self, *args, **kwargs):
                raise AssertionError('Oversized context must not reach provider')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'app.py').write_text('VERSION = 1\n')
            config = {'mode': 'agent', 'goal': 'Upgrade version',
                'agent': {'max_context_bytes': 1},
                'acceptance': [[sys.executable, '-c', 'pass']]}
            result = run(config, root, root/'.keel/run', model=Model())
            self.assertEqual(result['failure']['category'], 'budget_exhausted')
            self.assertEqual(result['budget']['model_calls'], 0)
            self.assertEqual((root/'app.py').read_text(), 'VERSION = 1\n')

    def test_long_history_is_bounded_and_receipt_chain_retains_every_turn(self):
        stored = {}
        def archive(payload):
            reference = len(stored) + 100
            stored[reference] = payload
            return reference
        header = [{'role': 'system', 'content': 'Original rules'}, {'role': 'user', 'content': 'Original goal'}]
        history = BoundedConversation(header, 1200, archive)
        for turn in range(40):
            note = {'error': 'failed attempt'} if turn % 2 else {'changed': 'app.py'}
            history.add('action-' + str(turn), {'text': '代码证据' * 500}, turn, note)
            messages, metrics = history.build(200)
            self.assertLessEqual(size(messages) + 200, 1200)
            self.assertEqual(messages[:2], header)
        references, index = [], history.index
        while index is not None:
            references.append(stored[index]['receipt_fact'])
            index = stored[index]['previous_index_fact']
        self.assertEqual(set(references), set(range(40)))
        self.assertEqual(metrics['total_archived_turns'], 40)
        self.assertIn('failed attempt', json.dumps(messages))

    def test_oversized_immutable_input_is_rejected_and_edits_remove_stale_previews(self):
        history = BoundedConversation([{'role': 'system', 'content': 'rules'}], 2000, lambda payload: 99)
        history.add('read', {'text': 'OLD_SOURCE'}, 1, {'ok': True})
        history.invalidate_evidence()
        messages, metrics = history.build()
        self.assertNotIn('OLD_SOURCE', json.dumps(messages))
        self.assertTrue(metrics['source_changed'])
        with self.assertRaises(BudgetExceeded):
            BoundedConversation([{'role': 'user', 'content': 'x'*3000}], 2000, lambda payload: 1).build()

    def test_runtime_compacts_long_evidence_and_preserves_real_edit_and_verification(self):
        class Model:
            def __init__(self):
                self.calls = []
                self.actions = iter([
                    {'final': {'summary': 'Upgrade version', 'files': ['app.py']}},
                    {'final': [{'id': 'fix', 'description': 'Upgrade version', 'files': ['app.py']}]},
                    {'tool': 'read_file', 'arguments': {'path': 'app.py'}},
                    {'tool': 'read_lines', 'arguments': {'path': 'app.py', 'start_line': 401, 'end_line': 401}},
                    {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}},
                    {'final': 'Changed version'}])
            def complete(self, messages, **kwargs):
                self.calls.append(json.loads(json.dumps(messages)))
                return Reply(json.dumps(next(self.actions)), 10)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'app.py').write_text('# filler\n'*400 + 'VERSION = 1\n')
            model = Model()
            config = {'mode': 'agent', 'goal': 'Upgrade version in app.py',
                'agent': {'max_context_bytes': 5000}, 'budget': {'max_tokens': 100000},
                'acceptance': [[sys.executable, '-c', 'import app; assert app.VERSION == 2']]}
            result = run(config, root, root/'.keel/run', model=model)
            self.assertEqual(result['status'], 'passed')
            self.assertTrue(all(size(messages) <= 5000 for messages in model.calls))
            self.assertIn('archive_index_fact', json.dumps(model.calls[3]))
            self.assertTrue(any(fact['summary'] == 'Conversation archive' for fact in result['facts']))
            self.assertEqual(model.calls[3][1]['content'], model.calls[2][1]['content'])
