import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from contextlib import asynccontextmanager
from unittest.mock import patch
from compass.service import CompassService
from compass.mcp import StdioServer


class TextMcpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        subprocess.run(['git','init',str(self.repo)],capture_output=True,check=True)
        (self.repo/'api.py').write_text('def packaging(): return 1\n')
        (self.repo/'guide.rst').write_text('Packaging guide\n===============\nUse the configured backend.\n')
        (self.repo/'pyproject.toml').write_text('[build-system]\nrequires=["setuptools"]\n')
        subprocess.run(['git','-c','safe.directory='+str(self.repo),'add','.'],cwd=self.repo,capture_output=True,check=True)
        self.service=CompassService(self.repo,enable_text_search=True,text_index=self.root/'cache.sqlite')

    def test_opt_in_discovery_and_schema_bounds(self):
        self.assertNotIn('search_text',[t['name'] for t in CompassService(self.repo).tools])
        self.assertIn('search_text',[t['name'] for t in self.service.tools])
        for args in [dict(query='packaging',max_lines=101),dict(query='x',max_bytes=0),dict(query='x',file='../secret')]:
            with self.assertRaises(ValueError):self.service.call('search_text',args)
        with self.assertRaises(ValueError):CompassService(self.repo,enable_text_search=True,text_index=self.repo/'cache.sqlite')

    def test_read_only_bounded_result_cache_reuse_and_updated_evidence(self):
        result=self.service.call('search_text',dict(query='packaging',max_lines=2,max_bytes=1024))
        self.assertTrue(result['results']);self.assertLessEqual(result['emitted_lines'],2)
        self.assertLessEqual(result['source_bytes'],1024)
        self.assertTrue(all(r['path']!='api.py' for r in result['results']))
        self.assertFalse((self.repo/'.compass').exists())
        self.assertEqual(result['usage']['model_calls'],0)
        self.assertTrue(result['untrusted_content'])
        second=self.service.call('search_text',dict(query='setuptools'))
        self.assertEqual(second['index_updates']['reused_files'],3)
        (self.repo/'pyproject.toml').write_text('[build-system]\nrequires=["otherbackend"]\n')
        changed=self.service.call('search_text',dict(query='otherbackend'))
        self.assertIn('otherbackend',changed['results'][0]['text'])
        self.assertNotEqual(changed['source_manifest_sha256'],second['source_manifest_sha256'])

    def test_single_oversized_line_is_not_silently_cut_into_fake_evidence(self):
        (self.repo/'guide.rst').write_text('packaging '+'x'*2000+'\n')
        result=self.service.call('search_text',dict(query='packaging',max_bytes=1024))
        self.assertTrue(result['truncated']);self.assertEqual(result['results'],[])

    def test_actual_stdio_tool_is_callable_and_hidden_without_opt_in(self):
        messages=[dict(jsonrpc='2.0',id=1,method='initialize',params=dict(protocolVersion='2025-11-25',capabilities={},clientInfo=dict(name='test',version='1'))),
                  dict(jsonrpc='2.0',method='notifications/initialized'),dict(jsonrpc='2.0',id=2,method='tools/list'),
                  dict(jsonrpc='2.0',id=3,method='tools/call',params=dict(name='search_text',arguments=dict(query='setuptools')))]
        process=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'examples/compass_mcp_entry.py'),'serve','--repo','.',
            '--enable-text-search','--text-index',str(self.root/'stdio.sqlite')],
            input='\n'.join(json.dumps(m) for m in messages)+'\n',text=True,encoding='utf-8',
            capture_output=True,timeout=30,cwd=self.repo)
        self.assertEqual(process.returncode,0,process.stderr)
        replies=[json.loads(s) for s in process.stdout.splitlines()]
        self.assertIn('search_text',[t['name'] for t in replies[1]['result']['tools']])
        self.assertFalse(replies[2]['result']['isError'])
        self.assertIn('setuptools',replies[2]['result']['structuredContent']['results'][0]['text'])

    @unittest.skipUnless(importlib.util.find_spec('mcp'),'Official MCP SDK required')
    def test_official_sdk_keel_gateway_role_policy_and_ledger(self):
        import anyio
        from mcp.shared.memory import create_client_server_memory_streams
        from mcp.shared.message import SessionMessage
        from mcp.types import JSONRPCMessage
        from keel.core import Budget,Limits,Ledger,Trace,PolicyDenied
        from keel.workspace import Workspace
        from keel.gateway import ToolGateway
        from keel.mcp_client import McpTools
        @asynccontextmanager
        async def connection(client,spec,stderr):
            # Actual handler and official SDK messages; only OS transport replaced.
            session=StdioServer(self.service)
            async with create_client_server_memory_streams() as (client_streams,streams):
                async def serve():
                    async for message in streams[0]:
                        response=session.handle(message.message.model_dump(by_alias=True,exclude_none=True))
                        if response is not None:
                            await streams[1].send(SessionMessage(JSONRPCMessage.model_validate(response)))
                async with anyio.create_task_group() as group:
                    group.start_soon(serve)
                    try:yield client_streams
                    finally:group.cancel_scope.cancel()
        ledger=Ledger(self.root/'ledger.sqlite')
        self.addCleanup(ledger.close)
        ws=Workspace(self.repo,Budget(Limits(max_tool_calls=3,max_wallclock=30)),ledger,Trace(self.root/'trace.jsonl'))
        config=json.loads((Path(__file__).parents[1]/'examples/mcp-compass-text.json').read_text())
        ws.mcp_tools=McpTools(config,ws)
        scout=ToolGateway('scout',ws);planner=ToolGateway('planner',ws)
        self.assertIn('mcp__compass__search_text',scout.catalog())
        self.assertNotIn('mcp__compass__search_text',planner.catalog())
        with self.assertRaises(PolicyDenied):planner.call('mcp__compass__search_text',{'query':'setuptools'})
        with patch.object(McpTools,'_connection',connection):
            result=scout.call('mcp__compass__search_text',{'query':'setuptools','max_lines':5})
        self.assertIn(result['fact_id'],scout.visible_facts)
        self.assertIn('setuptools',json.dumps(ledger.recall(result['fact_id'])))
        self.assertFalse((self.repo/'.compass').exists())


if __name__=='__main__':unittest.main()
