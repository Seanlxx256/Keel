import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from contextlib import asynccontextmanager
from types import SimpleNamespace

from keel.core import Budget, BudgetExceeded, Ledger, Limits, PolicyDenied, Trace
from keel.gateway import ToolGateway
from keel.mcp_client import McpToolError, McpTools, validate_servers
from keel.workspace import Workspace


class McpClientTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ledger = Ledger(self.root / 'ledger.sqlite')
        self.addCleanup(self.ledger.close)
        self.ws = Workspace(self.root, Budget(Limits()), self.ledger, Trace(self.root / 'trace.jsonl'))
        self.servers = {'repo': {'command': sys.executable, 'args': [],
            'tools': {'find_symbol': {'roles': ['scout'], 'description': '{"name": "symbol"} -> symbols'}}}}
        self.ws.mcp_tools = McpTools(self.servers, self.ws)

    def test_role_allowlist_and_evidence_isolation(self):
        async def invoke(*args):
            return {'content': [{'type': 'text', 'text': 'evidence'}]}
        scout, planner = ToolGateway('scout', self.ws), ToolGateway('planner', self.ws)
        alias = 'mcp__repo__find_symbol'
        self.assertIn(alias, scout.catalog())
        self.assertNotIn(alias, planner.catalog())
        with patch.object(McpTools, '_invoke', side_effect=invoke) as call:
            with self.assertRaises(PolicyDenied):
                planner.call(alias, {'name': 'fetch'})
            call.assert_not_called()
            result = scout.call(alias, {'name': 'fetch'})
        self.assertEqual(self.ws.budget.tool_calls, 1)
        self.assertIn(result['fact_id'], scout.visible_facts)
        self.assertNotIn(result['fact_id'], planner.visible_facts)
        events = [json.loads(line) for line in self.ws.trace.path.read_text().splitlines()]
        self.assertTrue(any(e.get('transport') == 'mcp_stdio' for e in events))

    def test_timeout_error_and_exhausted_budget(self):
        async def slow(*args):
            await asyncio.sleep(10)
        self.servers['repo']['timeout'] = .01
        with patch.object(McpTools, '_invoke', side_effect=slow):
            with self.assertRaisesRegex(McpToolError, 'TimeoutError'):
                ToolGateway('scout', self.ws).call('mcp__repo__find_symbol', {})
        self.ws.budget.tool_calls = self.ws.budget.limits.max_tool_calls
        with patch.object(McpTools, '_invoke') as invoke:
            with self.assertRaises(BudgetExceeded):
                ToolGateway('scout', self.ws).call('mcp__repo__find_symbol', {})
            invoke.assert_not_called()

    def test_bad_config_is_rejected_before_starting_process(self):
        for servers in [[], {'bad__name': self.servers['repo']},
                        {'x': {'command': 'python', 'tools': {}}},
                        {'x': {**self.servers['repo'], 'timeout': float('nan')}},
                        {'x': {**self.servers['repo'], 'shell': True}}]:
            with self.assertRaises(ValueError):
                validate_servers(servers)

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'Official MCP SDK is not installed')
    def test_sdk_boundary_validates_schema_and_server_errors(self):
        @asynccontextmanager
        async def transport(*args, **kwargs):
            yield object(), object()

        session = AsyncMock()
        session.list_tools.return_value = SimpleNamespace(tools=[SimpleNamespace(
            name='find_symbol', inputSchema={'type': 'object', 'required': ['name'],
            'properties': {'name': {'type': 'string'}}, 'additionalProperties': False})], nextCursor=None)
        session.call_tool.return_value = SimpleNamespace(isError=True)
        context = AsyncMock()
        context.__aenter__.return_value = session
        gateway = ToolGateway('scout', self.ws)
        with patch('mcp.client.stdio.stdio_client', transport), patch('mcp.ClientSession', return_value=context):
            with self.assertRaisesRegex(McpToolError, 'input schema'):
                gateway.call('mcp__repo__find_symbol', {'name': 7})
            session.call_tool.assert_not_called()
            with self.assertRaisesRegex(McpToolError, 'tool error'):
                gateway.call('mcp__repo__find_symbol', {'name': 'fetch'})
        self.assertEqual(context.__aexit__.await_count, 2)

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'Official MCP SDK is not installed')
    def test_real_compass_stdio_schema_errors_and_shutdown(self):
        from compass.index import build_index
        (self.root / 'api.py').write_text('def fetch(value):\n    return value\n')
        build_index(self.root, parser='python-ast')
        package = str(Path(__file__).resolve().parents[1])
        self.servers['repo']['args'] = ['-c',
            'import sys; sys.path.insert(0, ' + repr(package) + '); from compass.cli import main; raise SystemExit(main())',
            'serve', '--repo', str(self.root)]
        gateway = ToolGateway('scout', self.ws)
        result = gateway.call('mcp__repo__find_symbol', {'name': 'fetch'})
        payload = self.ledger.recall(result['fact_id'])
        self.assertFalse(payload['isError'])
        self.assertEqual(payload['structuredContent']['results'][0]['name'], 'fetch')
        with self.assertRaises(McpToolError):
            gateway.call('mcp__repo__find_symbol', {'name': 7})
        # A new request after an error proves contexts have shut down cleanly.
        self.assertIn('fact_id', gateway.call('mcp__repo__find_symbol', {'name': 'fetch'}))
