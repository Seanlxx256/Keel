import json
import tempfile
import unittest
from pathlib import Path

from keel.core import Budget, BudgetExceeded, Ledger, Limits, PolicyDenied, Trace
from keel.gateway import ToolGateway
from keel.workspace import Workspace


class GatewayTests(unittest.TestCase):
    def test_late_file_window_and_unchanged_read_do_not_repeat_prefix(self):
        self.budget.limits.max_tool_calls = 20
        text = ''.join(f'line_{i} = {i}\n' for i in range(1, 801))
        (self.root/'app.py').write_text(text)
        gateway = ToolGateway('implementer', self.ws, allowed_files=['app.py'])
        first = gateway.call('read_file', {'path': 'app.py'})
        repeated = gateway.call('read_file', {'path': 'app.py'})
        self.assertEqual(repeated['fact_id'], first['fact_id'])
        self.assertTrue(repeated['unchanged'])
        self.assertNotIn('preview', repeated)
        window = gateway.call('read_lines', {'path': 'app.py', 'start_line': 715, 'end_line': 720})
        self.assertIn('line_717 = 717', window['text'])
        self.assertNotIn('line_1 = 1\n', window['text'])
        self.assertEqual(window['next_line'], 721)
        self.assertEqual(window['total_lines'], 800)
        (self.root/'app.py').write_text(text + '# changed\n')
        changed = gateway.call('read_file', {'path': 'app.py'})
        self.assertNotEqual(changed['fact_id'], first['fact_id'])
        for bounds in [(0, 10), (5, 4), (1, 81), (900, 901)]:
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                gateway.call('read_lines', {'path': 'app.py', 'start_line': bounds[0], 'end_line': bounds[1]})

    def test_action_schema_rejects_incomplete_replace_and_readonly_write(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('jsonschema is required for provider-schema validation')
        implementer = ToolGateway('implementer', self.ws, allowed_files=['app.py'])
        schema = implementer.action_schema()
        jsonschema.Draft202012Validator.check_schema(schema)
        valid = {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': '1', 'new': '2'}}
        jsonschema.validate(valid, schema)
        for action in [
            {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': '1'}},
            {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': '1', 'new': 2}},
            {'tool': 'read_file', 'arguments': {'path': 'app.py', 'new': '2'}},
        ]:
            with self.subTest(action=action), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(action, schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(valid, ToolGateway('scout', self.ws).action_schema())
        self.assertEqual(self.budget.tool_calls, 0)
        self.assertEqual((self.root/'app.py').read_text(), 'VERSION = 1\n')

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'app.py').write_text('VERSION = 1\n')
        self.ledger = Ledger(self.root / 'ledger.sqlite')
        self.addCleanup(self.ledger.close)
        self.trace = Trace(self.root / 'trace.jsonl')
        self.budget = Budget(Limits(max_tool_calls=1))
        self.ws = Workspace(self.root, self.budget, self.ledger, self.trace)

    def events(self):
        return [json.loads(line) for line in self.trace.path.read_text().splitlines()
                if 'gateway_call_' in line]

    def test_direct_boundary_denies_write_and_keeps_correlated_trace(self):
        gateway = ToolGateway('scout', self.ws)
        with self.assertRaises(PolicyDenied):
            gateway.call('replace', {'path': 'app.py', 'old': '1', 'new': '2'})
        start, end = self.events()
        self.assertEqual(start['call_id'], end['call_id'])
        self.assertEqual(end['status'], 'denied')
        self.assertEqual(self.budget.tool_calls, 0)
        self.assertEqual((self.root / 'app.py').read_text(), 'VERSION = 1\n')

    def test_recall_is_session_scoped_and_budget_is_not_double_charged(self):
        gateway = ToolGateway('scout', self.ws)
        result = gateway.call('read_file', {'path': 'app.py'})
        self.assertEqual(self.budget.tool_calls, 1)
        other = ToolGateway('planner', self.ws)
        with self.assertRaises(PolicyDenied):
            other.call('recall', {'fact_id': result['fact_id']})
        with self.assertRaises(BudgetExceeded):
            gateway.call('recall', {'fact_id': result['fact_id']})
        self.assertEqual(self.events()[-1]['error_type'], 'BudgetExceeded')
        self.assertEqual(self.events()[1]['status'], 'completed')

    def test_malformed_arguments_fail_before_workspace_access(self):
        gateway = ToolGateway('implementer', self.ws, allowed_files=['app.py'])
        for tool, args in [('list_files', {'unexpected': 1}),
                           ('recall', {'fact_id': True}),
                           ('replace', {'path': 'app.py', 'old': '1', 'new': 2})]:
            with self.assertRaises((ValueError, PolicyDenied)):
                gateway.call(tool, args)
        self.assertEqual(self.budget.tool_calls, 0)
        self.assertTrue(all(event['status'] in {'failed', 'denied'}
                            for event in self.events() if 'status' in event))

    def test_recall_cannot_read_past_end_of_evidence(self):
        self.budget.limits.max_tool_calls = 10
        gateway = ToolGateway('scout', self.ws)
        result = gateway.call('read_file', {'path': 'app.py'})
        with self.assertRaisesRegex(ValueError, 'outside stored evidence'):
            gateway.call('recall', {'fact_id': result['fact_id'], 'offset': 4000})
