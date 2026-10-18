import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from compass.index import build_index
from compass.mcp import StdioServer
from compass.service import CompassService


def initialize(version="2025-11-25"):
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}


class McpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "api.py").write_text('def fetch(value):\n    """Read data 🧭."""\n    return value\n', encoding="utf-8")
        build_index(self.root, parser="python-ast")
        self.server = StdioServer(CompassService(self.root))

    def ready(self, version="2025-11-25"):
        response = self.server.handle(initialize(version))
        self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return response

    def request(self, method, params=None):
        return self.server.handle({"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}})

    def test_initialization_and_capabilities(self):
        result = self.ready()["result"]
        self.assertEqual(result["serverInfo"]["name"], "repo-intel")
        self.assertIn("tools", result["capabilities"])
        tools = self.request("tools/list")["result"]["tools"]
        self.assertEqual({tool["name"] for tool in tools}, {"find_symbol", "search_code", "impact_analysis", "get_context", "get_symbols_overview"})

    def test_tools_unavailable_until_initialized_notification(self):
        self.assertIn("error", self.request("tools/list"))
        self.server.handle(initialize())
        self.assertIn("error", self.request("tools/list"))

    def test_tool_output_is_structured_and_text_for_compatibility(self):
        self.ready()
        result = self.request("tools/call", {"name": "find_symbol", "arguments": {"name": "fetch"}})["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        self.assertIn("🧭", result["structuredContent"]["results"][0]["docstring"])

    def test_old_protocol_omits_new_structured_fields(self):
        self.ready("2024-11-05")
        result = self.request("tools/call", {"name": "find_symbol", "arguments": {"name": "fetch"}})["result"]
        self.assertNotIn("structuredContent", result)
        self.assertNotIn("outputSchema", self.request("tools/list")["result"]["tools"][0])

    def test_unknown_tool_is_protocol_error_but_bad_arguments_are_tool_errors(self):
        self.ready()
        self.assertEqual(self.request("tools/call", {"name": "unknown"})["error"]["code"], -32602)
        result = self.request("tools/call", {"name": "get_context", "arguments": {"file": "api.py", "line": False}})
        self.assertTrue(result["result"]["isError"])

    def test_impact_analysis_does_not_silently_run_without_model(self):
        self.ready()
        result = self.request("tools/call", {"name": "impact_analysis", "arguments": {"change": "upgrade api"}})["result"]
        self.assertTrue(result["isError"])
        self.assertIn("requires a configured chat model", result["content"][0]["text"])

    def test_invalid_rpc_ids_and_batches_are_rejected(self):
        self.assertEqual(self.server.handle([])["error"]["code"], -32600)
        result = self.server.handle({"jsonrpc": "2.0", "id": [], "method": 1})
        self.assertIsNone(result["id"])

    def test_oversized_frame_recovers_at_next_message(self):
        source = io.BytesIO(b"x" * 100 + b"\n" + b'{"jsonrpc":"2.0","id":3,"method":"ping"}\n')
        sink = io.StringIO()
        with patch("compass.mcp.MAX_FRAME", 64):
            self.server.serve(source, sink)
        responses = [json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertEqual(responses[1]["result"], {})

    def test_stdio_roundtrip_in_real_subprocess_and_clean_eof_shutdown(self):
        messages = [initialize(), {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "find_symbol", "arguments": {"name": "fetch"}}}]
        completed = subprocess.run([sys.executable, "-m", "compass", "serve", "--repo", str(self.root)],
                                   input="\n".join(json.dumps(message) for message in messages) + "\n", text=True,
                                   encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=Path(__file__).resolve().parents[1], timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([response["id"] for response in responses], [1, 2, 3])
        self.assertFalse(responses[2]["result"]["isError"])
        self.assertEqual(responses[2]["result"]["structuredContent"]["results"][0]["name"], "fetch")


if __name__ == "__main__":
    unittest.main()
