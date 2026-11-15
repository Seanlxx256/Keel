"""Real loopback control HTTP + official MCP SDK memory transport integration."""
from contextlib import asynccontextmanager
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from keel.control_service import ControlService, make_server
from keel.core import Budget, Ledger, Limits, Trace
from keel.gateway import ToolGateway
from keel.governance import GovernanceUnavailable
from keel.mcp_broker import RoutedMcpTools
from keel.mcp_client import McpTools, McpTransportUnavailable
from keel.remote_governance import RemoteSession
from keel.workspace import Workspace


@unittest.skipUnless(importlib.util.find_spec('mcp') and importlib.util.find_spec('jsonschema'),
                     'Official MCP SDK and schema validator are optional')
class McpBrokerSdkTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        (self.repo/'a.py').write_text('value = 1\n',encoding='utf-8')
        self.alias='mcp__nav__lookup';self.calls=[];self.entered=threading.Event();self.block=False
        config={'path':str(self.root/'control.sqlite'),
            'scopes':{'scope':{'max_tokens':1000,'max_model_calls':10,'lease_seconds':900}},
            'principals':[{'id':'worker','task_id':'task','scope':'scope','token_env':'KEEL_SDK_BROKER_TEST',
                           'require_mcp_broker':True,'tools':{'scout':[self.alias]}}],
            'read_broker':{'evidence_root':str(self.root/'evidence'),
                           'repositories':{'task':{'root':str(self.repo),'files':['a.py']}}},
            'mcp_broker':{'tasks':{'task':{'servers':{'nav':{'command':sys.executable,'timeout':5,
                'tools':{'lookup':{'roles':['scout'],'description':'Look up a symbol',
                    'read_only':True,'input_schema':{'type':'object','properties':{'name':{'type':'string'}},
                        'required':['name'],'additionalProperties':False}}}}},'path_arguments':{self.alias:[]}}}}}
        env=patch.dict(os.environ,{'KEEL_SDK_BROKER_TEST':'t'*48});env.start();self.addCleanup(env.stop)
        from mcp.server.fastmcp import FastMCP
        self.sdk=FastMCP('broker-memory-fixture')
        @self.sdk.tool()
        async def lookup(name:str)->dict:
            self.calls.append(name);self.entered.set()
            if self.block:await asyncio.Event().wait()
            return {'name':name,'fixture':'official SDK in-memory server'}
        from mcp.shared.memory import create_client_server_memory_streams
        import anyio
        @asynccontextmanager
        async def connection(client,spec,stderr):
            async with create_client_server_memory_streams() as (client_streams,server_streams):
                async with anyio.create_task_group() as group:
                    group.start_soon(self.sdk._mcp_server.run,*server_streams,self.sdk._mcp_server.create_initialization_options())
                    try:yield client_streams
                    finally:group.cancel_scope.cancel()
        connection_patch=patch.object(McpTools,'_connection',connection)
        connection_patch.start();self.addCleanup(connection_patch.stop)
        self.service=ControlService(config);self.server=make_server(self.service)
        self.server_thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.server_thread.start()
        self.addCleanup(self.stop)
        endpoint='http://127.0.0.1:'+str(self.server.server_address[1])
        self.remote=RemoteSession.begin({'endpoint':endpoint,'token_env':'KEEL_SDK_BROKER_TEST','task_id':'task',
                                         'timeout_seconds':2},'input',30)
        self.ledger=Ledger(self.root/'worker.sqlite');self.addCleanup(self.ledger.close)
        self.ws=Workspace(self.repo,Budget(Limits(max_wallclock=20)),self.ledger,Trace(self.root/'worker-trace.jsonl'))
        self.ws.governance=self.remote
        self.ws.mcp_tools=RoutedMcpTools(McpTools({},self.ws),self.ws)
        self.gateway=ToolGateway('scout',self.ws)

    def stop(self):
        self.service.close(timeout=2)
        self.server.shutdown();self.server.server_close();self.server_thread.join(timeout=2)

    def test_preflight_crosses_http_without_sdk_tool_call(self):
        with patch('keel.mcp_preflight.check_host',return_value={'status':'unavailable','model_calls':0,'mcp_tool_calls':0}) as probe:
            result=self.remote.preflight_mcp(2)
        probe.assert_called_once()
        self.assertEqual(result['authority'],'controller host capability probe')
        self.assertEqual(result['status'],'unavailable')
        self.assertEqual(self.calls,[])
        self.assertIsNone(self.remote.pending)

    def test_http_sdk_callback_artifact_and_local_fact_import(self):
        result=self.gateway.call(self.alias,{'name':'value'})
        observation=self.ledger.recall(result['fact_id'])
        self.assertEqual(self.calls,['value'])
        self.assertEqual(observation['authority'],'controller MCP invocation with untrusted server output')
        self.assertEqual(observation['alias'],self.alias)
        lifecycle=list((self.root/'evidence').glob('*/mcp-*/lifecycle.json'))
        self.assertEqual(len(lifecycle),1)
        import json
        receipt=json.loads(lifecycle[0].read_text(encoding='utf-8'))
        self.assertTrue(receipt['request_finished']);self.assertTrue(receipt['direct_children_exited'])

    def test_out_of_band_http_cancel_preserves_unknown_effect_and_pending_id(self):
        self.block=True;errors=[]
        def invoke():
            try:self.gateway.call(self.alias,{'name':'blocked'})
            except BaseException as error:errors.append(error)
        thread=threading.Thread(target=invoke,daemon=True);thread.start()
        try:
            self.assertTrue(self.entered.wait(timeout=3))
            original=self.remote.pending['operation_id']
            receipt=self.remote.cancel_pending_mcp()
            self.assertEqual(receipt['status'],'cancel_requested')
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertIsInstance(errors[0],GovernanceUnavailable)
            self.assertEqual(self.remote.pending['operation_id'],original)
            with self.service.store.transaction() as db:
                row=db.execute('SELECT status FROM broker_mcp_requests WHERE operation_id=?',(original,)).fetchone()
            self.assertEqual(row['status'],'inflight');self.assertEqual(self.calls,['blocked'])
        finally:
            self.service.mcp_broker.request_stop();thread.join(timeout=2)

    def test_http_preserves_known_transport_stage_without_invoking_tool(self):
        @asynccontextmanager
        async def unavailable(*args):
            raise PermissionError(13,'private OS message')
            yield  # Defines the async context protocol, never reached.
        with patch.object(McpTools,'_connection',unavailable):
            with self.assertRaises(McpTransportUnavailable) as caught:
                self.gateway.call(self.alias,{'name':'value'})
        self.assertEqual(caught.exception.failure['stage'],'transport_start')
        self.assertFalse(caught.exception.failure['tool_dispatch_started'])
        self.assertNotIn('private OS message',str(caught.exception))
        self.assertEqual(self.calls,[]);self.assertIsNone(self.remote.pending)


if __name__=='__main__':unittest.main()
