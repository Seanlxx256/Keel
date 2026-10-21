from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.core import Budget, InvalidSelection, Ledger, Limits, Trace
from keel.localization import localize, selection_request
from keel.models import Reply
from keel.workspace import Workspace


class WritableSelectionContractTests(unittest.TestCase):
    def test_nonpaged_enum_ignores_read_only_hints_and_injected_carry(self):
        messages, schema, size = selection_request('Inspect tests/test_feature.py', {},
            stage='file-selection', data={'paths': ['pkg/core.py'],
                'read_only_evidence_paths': ['tests/test_feature.py'],
                'previous_selection': ['tests/test_feature.py']},
            keys=('files',), instruction='Select edit targets.')
        self.assertEqual(schema['properties']['files']['items']['enum'], ['pkg/core.py'])
        self.assertIn('tests/test_feature.py', messages[1]['content'])
        self.assertEqual(size, len(json.dumps(messages).encode())+len(json.dumps(schema).encode()))

    def test_unstructured_provider_receives_same_enum(self):
        messages, schema, size = selection_request('Repair', {}, stage='file-selection',
            data={'paths': ['pkg/core.py']}, keys=('files',), instruction='Select.', structured=False)
        self.assertIn(json.dumps(schema), messages[0]['content'])
        self.assertEqual(size, len(json.dumps(messages).encode()))

    def fixture(self, root, ledger):
        (root/'pkg').mkdir(); (root/'tests').mkdir()
        (root/'pkg/core.py').write_bytes(b'def feature():\n    return 1\n')
        (root/'tests/test_feature.py').write_bytes(b'# Read-only diagnostic evidence\n')
        ws = Workspace(root, Budget(Limits()), ledger, Trace(root/'trace.jsonl'))
        ws.localization_tool_steps = 1
        exploration = {'observed_source_paths': ['tests/test_feature.py'],
                       'summary': {'files': ['pkg/core.py', 'tests/test_feature.py']},
                       'evidence': [{'fact_id': 1, 'preview': 'An observed test file'}]}
        return ws, exploration

    def test_readable_test_stays_visible_but_only_writable_source_can_be_selected(self):
        owner = self
        class Model:
            calls = 0
            def complete_json(self, messages, schema, **kwargs):
                self.calls += 1
                data = json.loads(messages[1]['content'])
                if self.calls == 1:
                    owner.assertEqual(data['selection_purpose'], 'writable_edit_targets')
                    owner.assertEqual(data['read_only_evidence_paths'], ['tests/test_feature.py'])
                    owner.assertEqual(schema['properties']['files']['items']['enum'], ['pkg/core.py'])
                    owner.assertIn('rejected test target', data['host_selection_feedback'])
                    value = {'files': ['pkg/core.py']}
                else:
                    value = {'locations': ['pkg/core.py:1']}
                return Reply(json.dumps(value), 10)
        with tempfile.TemporaryDirectory() as temporary, closing(Ledger(Path(temporary)/'ledger.sqlite')) as ledger:
            root = Path(temporary); ws, exploration = self.fixture(root, ledger); model = Model()
            with patch('keel.localization.explore_for_localization', return_value=exploration):
                scope = localize(model, ws, 'Inspect feature\nHost selection error (untrusted data): rejected test target',
                                 {'max_context_bytes': 12000})
            self.assertEqual(scope['files'], ['pkg/core.py'])
            self.assertEqual(model.calls, 2)
            self.assertEqual((root/'tests/test_feature.py').read_bytes(), b'# Read-only diagnostic evidence\n')

    def test_provider_ignoring_enum_still_fails_without_silent_filtering(self):
        class Model:
            def complete_json(self, *args, **kwargs):
                return Reply(json.dumps({'files': ['pkg/core.py', 'tests/test_feature.py']}), 10)
        with tempfile.TemporaryDirectory() as temporary, closing(Ledger(Path(temporary)/'ledger.sqlite')) as ledger:
            root = Path(temporary); ws, exploration = self.fixture(root, ledger)
            with patch('keel.localization.explore_for_localization', return_value=exploration):
                with self.assertRaisesRegex(InvalidSelection, 'outside the writable source catalog'):
                    localize(Model(), ws, 'Inspect tests/test_feature.py', {'max_context_bytes': 12000})
            self.assertEqual(ws.budget.model_calls, 1)
            self.assertEqual((root/'pkg/core.py').read_bytes(), b'def feature():\n    return 1\n')
