import json
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from keel.core import Budget, Limits, BudgetExceeded, ModelError, PolicyDenied
from keel.models import Reply
from keel.repair import select_repair_evidence
from keel.proposals import proposal_request


class RepairSelectionTests(unittest.TestCase):
    def fixture(self, selection, mutate=False, limit=2):
        source = {'first.py': 'def first():\n    return 1\n', 'second.py': 'def second():\n    return 2\n'}
        workspace = SimpleNamespace(read=lambda name, **kw: {'value': source[name]}, ledger=Mock(),
                                    trace=Mock(), budget=Budget(Limits(max_model_calls=limit)))
        class Model:
            def complete_json(self, messages, **kwargs):
                if mutate:
                    source['second.py'] += '# changed\n'
                return Reply(json.dumps({'locations': selection}), 10)
        return workspace, Model(), {'files': list(source)}

    def test_omitted_file_can_be_explicitly_read_then_edited(self):
        workspace, model, scope = self.fixture(['second.py:1'])
        evidence = select_repair_evidence(model, workspace, 'repair', scope, [{'message': 'failed'}], {})
        self.assertEqual([e['path'] for e in evidence], ['second.py'])
        self.assertIn('return 2', evidence[0]['windows'][0]['text'])
        request, _, _ = proposal_request('repair', scope['files'], evidence, {})
        self.assertEqual(json.loads(request[1]['content'])['allowed_files'], ['second.py'])
        self.assertEqual(workspace.budget.report()['model_calls'], 1)

    def test_outside_scope_or_unknown_line_is_rejected(self):
        for chosen in (['outside.py:1'], ['second.py:99']):
            workspace, model, scope = self.fixture(chosen)
            with self.assertRaises(ModelError):
                select_repair_evidence(model, workspace, 'repair', scope, [], {})

    def test_changed_current_source_is_rejected(self):
        workspace, model, scope = self.fixture(['second.py:1'], mutate=True)
        with self.assertRaises(PolicyDenied):
            select_repair_evidence(model, workspace, 'repair', scope, [], {})

    def test_existing_budget_is_not_reset(self):
        workspace, model, scope = self.fixture(['second.py:1'], limit=1)
        workspace.budget.allow_model(10, 10)
        with self.assertRaises(BudgetExceeded):
            select_repair_evidence(model, workspace, 'repair', scope, [], {})
