import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from compass.index import build_index
from compass.mcp import StdioServer
from compass.service import CompassService


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'Official MCP SDK required')
class CompassSdkOverviewTests(unittest.TestCase):
    def test_official_client_calls_actual_compass_handler_over_memory_streams(self):
        import anyio
        from mcp import ClientSession
        from mcp.shared.memory import create_client_server_memory_streams
        from mcp.shared.message import SessionMessage
        from mcp.types import JSONRPCMessage
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'api.py').write_text('class Api:\n    def fetch(self):\n        return 42\n', encoding='utf-8')
            build_index(root, parser='python-ast')
            server = StdioServer(CompassService(root))
            async def probe():
                async with create_client_server_memory_streams() as (client, streams):
                    async def serve():
                        async for message in streams[0]:
                            request = message.message.model_dump(by_alias=True, exclude_none=True)
                            response = server.handle(request)
                            if response is not None:
                                await streams[1].send(SessionMessage(JSONRPCMessage.model_validate(response)))
                    async with anyio.create_task_group() as group:
                        group.start_soon(serve)
                        async with ClientSession(*client) as session:
                            await session.initialize()
                            tools = await session.list_tools()
                            self.assertIn('get_symbols_overview', [t.name for t in tools.tools])
                            result = await session.call_tool('get_symbols_overview', {'file': 'api.py', 'depth': 1})
                            self.assertFalse(result.isError)
                            data = result.structuredContent or json.loads(result.content[0].text)
                            self.assertEqual([r['qualname'] for r in data['results']], ['Api', 'Api.fetch'])
                            self.assertNotIn('return 42', json.dumps(data))
                            await session.send_ping()
                        group.cancel_scope.cancel()
            asyncio.run(asyncio.wait_for(probe(), timeout=20))
