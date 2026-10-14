import json
import tempfile
import unittest
from pathlib import Path

from keel.core import Budget, BudgetExceeded, Ledger, Limits, PolicyDenied, Trace
from keel.gateway import ToolGateway
from keel.workspace import Workspace


class GatewayTests(unittest.TestCase):
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
