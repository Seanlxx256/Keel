import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from keel.core import PolicyDenied
from keel.models import Reply
from keel.proposals import proposal_request, propose, InvalidProposal
import hashlib


class EvidenceScopeTests(unittest.TestCase):
    def test_declared_but_unshown_target_correction_cannot_write_unshown_file(self):
        text='VALUE = 1\n'
        evidence=[{'path':'shown.py','sha256':hashlib.sha256(text.encode()).hexdigest(),'windows':[]}]
        budget=Mock();budget.remaining=100
        workspace=SimpleNamespace(budget=budget,trace=Mock(),ledger=Mock(),
            read=Mock(return_value={'value':text}),path=Mock(),replace=Mock())
        model=Mock()
        model.complete_json.side_effect=[Reply(json.dumps({'summary':'bad','edits':[
            {'path':'omitted.py','old':'1','new':'2'}]}),10),
            Reply(json.dumps({'summary':'corrected','edits':[
            {'path':'shown.py','old':'1','new':'2'}]}),10)]
        result=propose(model,workspace,'repair',['shown.py','omitted.py'],evidence,{},validation_retries=1)
        self.assertEqual(result,'corrected')
        self.assertEqual(model.complete_json.call_count,2)
        workspace.replace.assert_called_once_with('shown.py','1','2')

    def test_request_lists_only_files_with_current_evidence(self):
        evidence = [{'path': 'shown.py', 'sha256': 'x', 'windows': []}]
        messages, _, _ = proposal_request('repair', ['shown.py', 'omitted.py'], evidence, {})
        self.assertEqual(json.loads(messages[1]['content'])['allowed_files'], ['shown.py'])

    def test_omitted_file_edit_is_denied_before_any_write_not_key_error(self):
        text = 'VALUE = 1\n'
        evidence = [{'path': 'shown.py', 'sha256': hashlib.sha256(text.encode()).hexdigest(), 'windows': []}]
        budget = Mock()
        budget.remaining = 100
        workspace = SimpleNamespace(budget=budget, trace=Mock(), ledger=Mock(),
                                    read=Mock(return_value={'value': text}), path=Mock(), replace=Mock())
        model = Mock()
        model.complete_json.return_value = Reply(json.dumps({'summary': 'change', 'edits': [
            {'path': 'shown.py', 'old': '1', 'new': '2'},
            {'path': 'omitted.py', 'old': '1', 'new': '2'}]}), 10)
        with self.assertRaisesRegex(InvalidProposal, 'current evidence scope'):
            propose(model, workspace, 'repair', ['shown.py', 'omitted.py'], evidence, {})
        workspace.replace.assert_not_called()

    def test_evidence_cannot_expand_declared_scope(self):
        with self.assertRaises(PolicyDenied):
            proposal_request('repair', ['shown.py'], [{'path': 'other.py'}], {})
