"""MCP host-stage classification and authorized agent fallback contracts."""
import copy
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.agents import AgentSession
from keel.core import Budget, Ledger, Limits, Trace
from keel.governance import GovernanceUnavailable
from keel.mcp_client import McpToolError, McpTools, McpTransportUnavailable, request_phase
from keel.models import Reply
from keel.workspace import Workspace


class McpFailureStageTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);repo=self.root/'repo';repo.mkdir()
        (repo/'app.py').write_text('VERSION = 1\n')
        self.ledger=Ledger(self.root/'ledger.sqlite');self.addCleanup(self.ledger.close)
        self.ws=Workspace(repo,Budget(Limits(max_tokens=100000)),self.ledger,Trace(self.root/'trace.jsonl'))
        policy={'roles':['scout'],'description':'Look up code symbols'}
        self.ws.mcp_tools=McpTools({'repo':{'command':'fixture-not-launched','tools':{'lookup':policy,'other':policy}},
                                   'independent':{'command':'other-fixture-not-launched','tools':{'lookup':policy}}},self.ws)

    @staticmethod
    async def denied(*args):
        request_phase('transport_start')
        raise PermissionError(errno.EACCES,'private credential must not be echoed')

    def test_startup_permission_has_safe_phase_and_durable_receipt(self):
        with patch.object(McpTools,'_invoke',side_effect=self.denied):
            with self.assertRaises(McpTransportUnavailable) as caught:
                self.ws.mcp_tools.call('scout','mcp__repo__lookup',{})
        failure=caught.exception.failure
        self.assertEqual(failure['category'],'transport_unavailable')
        self.assertFalse(failure['tool_dispatch_started'])
        receipt=Path(failure['artifact']).read_text(encoding='utf-8')
        self.assertNotIn('private credential',receipt+str(caught.exception))
        self.assertEqual(json.loads(receipt)['os_error']['errno'],errno.EACCES)

    def test_nested_permission_is_not_misread_as_server_message(self):
        async def grouped(*args):
            request_phase('transport_start')
            raise ExceptionGroup('sensitive group',[PermissionError(errno.EACCES,'secret')])
        with patch.object(McpTools,'_invoke',side_effect=grouped):
            with self.assertRaises(McpTransportUnavailable) as caught:
                self.ws.mcp_tools.call('scout','mcp__repo__lookup',{})
        self.assertNotIn('sensitive group',str(caught.exception))

    def test_permission_after_dispatch_is_not_classified_as_startup(self):
        async def after(*args):
            request_phase('tool_dispatch',tool_dispatch_started=True)
            raise PermissionError(errno.EACCES,'secret')
        with patch.object(McpTools,'_invoke',side_effect=after):
            with self.assertRaises(McpToolError) as caught:self.ws.mcp_tools.call('scout','mcp__repo__lookup',{})
        self.assertNotIsInstance(caught.exception,McpTransportUnavailable)
        self.assertEqual(caught.exception.failure['category'],'tool_outcome_unknown')

    def test_schema_error_keeps_tool_error_type_and_message(self):
        async def invalid(*args):
            request_phase('validation')
            raise McpToolError('MCP arguments do not match the server input schema')
        with patch.object(McpTools,'_invoke',side_effect=invalid):
            with self.assertRaises(McpToolError) as caught:self.ws.mcp_tools.call('scout','mcp__repo__lookup',{})
        self.assertNotIsInstance(caught.exception,McpTransportUnavailable)
        self.assertIn('input schema',str(caught.exception))

    def test_missing_required_failure_receipt_aborts_instead_of_silent_fallback(self):
        with patch.object(McpTools,'_invoke',side_effect=self.denied):
            with patch('compass.progress.atomic_json',side_effect=OSError('disk unavailable')):
                with self.assertRaises(GovernanceUnavailable):self.ws.mcp_tools.call('scout','mcp__repo__lookup',{})

    def test_agent_pauses_same_server_and_reads_authorized_local_evidence(self):
        actions=iter([
            {'tool':'mcp__repo__lookup','arguments':{}},
            {'tool':'mcp__repo__other','arguments':{}},
            {'tool':'read_file','arguments':{'path':'app.py'}},
            {'final':{'summary':'Observed local source; external transport unavailable','files':['app.py']}}])
        messages=[]
        class Model:
            def complete(self,history,**kwargs):
                messages.append(copy.deepcopy(history));return Reply(json.dumps(next(actions)),1)
        session=AgentSession('scout',Model(),self.ws,max_steps=4,require_evidence=True,require_external_tool=True)
        with patch.object(McpTools,'_invoke',side_effect=self.denied) as invoke:
            result=session.execute({'goal':'inspect version'},'impact')
        invoke.assert_called_once();self.assertEqual(result['files'],['app.py'])
        self.assertIn('mcp__repo__other',session.paused_tools)
        self.assertNotIn('mcp__independent__lookup',session.paused_tools)
        self.assertEqual(self.ws.external_tool_metrics['mcp__repo__lookup']['completed'],0)
        first_feedback=json.loads(messages[1][-1]['content'])
        self.assertEqual(first_feedback['failure']['category'],'transport_unavailable')
        self.assertIn('paused_tools',first_feedback['strategy'])

    def test_request_stage_does_not_leak_into_later_calls(self):
        with patch.object(McpTools,'_invoke',side_effect=self.denied):
            with self.assertRaises(McpTransportUnavailable):self.ws.mcp_tools.call('scout','mcp__repo__lookup',{})
        async def unrelated(*args):raise PermissionError(errno.EACCES,'secret')
        with patch.object(McpTools,'_invoke',side_effect=unrelated):
            with self.assertRaises(McpToolError) as caught:self.ws.mcp_tools.call('scout','mcp__repo__lookup',{})
        self.assertNotIsInstance(caught.exception,McpTransportUnavailable)
        self.assertEqual(caught.exception.failure['stage'],'request')

    def test_agent_does_not_take_another_action_after_unknown_tool_effect(self):
        async def unknown(*args):
            request_phase('tool_dispatch',tool_dispatch_started=True)
            raise TimeoutError('reply lost')
        calls=[]
        class Model:
            def complete(self,history,**kwargs):
                calls.append(True)
                return Reply(json.dumps({'tool':'mcp__repo__lookup','arguments':{}}),1)
        session=AgentSession('scout',Model(),self.ws,max_steps=4)
        with patch.object(McpTools,'_invoke',side_effect=unknown) as invoke:
            with self.assertRaises(GovernanceUnavailable):session.execute({},'impact')
        self.assertEqual(len(calls),1);invoke.assert_called_once()


if __name__=='__main__':unittest.main()
