import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.check_mcp_host import execute


class McpHostCheckTests(unittest.TestCase):
    def test_missing_parent_published_before_first_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'missing'/'result'
            def sync(*args,**kwargs):
                self.assertEqual(json.loads((output/'report.json').read_text())['status'],'running')
                return {'status':'ok'}
            with patch('examples.check_mcp_host.probe_sync_stdio',side_effect=sync),patch(
                    'examples.check_mcp_host.probe_async_stdio',return_value={'status':'unavailable','winerror':5}):
                report=execute(output)
            self.assertEqual(report['observation'],'async_only_unavailable')
            self.assertEqual(report['checks']['async_stdio']['winerror'],5)

    def test_existing_results_preserved_without_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('examples.check_mcp_host.probe_sync_stdio') as probe:
                with self.assertRaises(FileExistsError):execute(Path(temp))
            probe.assert_not_called()

    def test_both_controls_pass_is_not_mcp_server_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('examples.check_mcp_host.probe_sync_stdio',return_value={'status':'ok'}),patch(
                    'examples.check_mcp_host.probe_async_stdio',return_value={'status':'ok'}):
                report=execute(Path(temp)/'out')
            self.assertEqual(report['status'],'available')
            self.assertEqual(report['mcp_tool_calls'],0)
