"""Host capability is checked before orchestration, without server dispatch."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from keel.ipc import probe_async_stdio
from keel.mcp_preflight import check_host, check_workspace, validate_policy
from keel.runtime import run


SERVERS={'repo':{'command':'must-not-launch','tools':{'lookup':{'roles':['scout'],'description':'Lookup'}}}}


class McpPreflightTests(unittest.TestCase):
    def test_policy_rejects_invalid_timeout_and_unknown_mode(self):
        for policy in ({'timeout_seconds':True},{'timeout_seconds':float('nan')},
                       {'timeout_seconds':16},{'mode':'bypass'},{'other':1}):
            with self.subTest(policy=policy),self.assertRaises(ValueError):validate_policy(policy)

    def test_no_servers_does_not_launch_diagnostic(self):
        with patch('keel.mcp_preflight.probe_async_stdio') as probe:
            self.assertEqual(check_host({})['status'],'not_required')
        probe.assert_not_called()

    def test_missing_dependency_does_not_launch_server_or_probe(self):
        with patch('keel.mcp_preflight.importlib.util.find_spec',return_value=None),patch('keel.mcp_preflight.probe_async_stdio') as probe:
            self.assertEqual(check_host(SERVERS)['status'],'unavailable')
        probe.assert_not_called()

    def test_probe_permission_failure_is_preserved(self):
        failure={'status':'unavailable','winerror':5}
        with patch('keel.mcp_preflight.importlib.util.find_spec',return_value=object()),patch('keel.mcp_preflight.probe_async_stdio',return_value=failure):
            report=check_host(SERVERS)
        self.assertEqual(report['checks']['async_stdio']['winerror'],5)
        self.assertEqual(report['model_calls'],0)

    def test_controller_is_not_certified_by_worker(self):
        ws=SimpleNamespace(budget=SimpleNamespace(check=lambda:None,remaining=10),
            mcp_tools=SimpleNamespace(servers={}),
            governance=SimpleNamespace(config={'mcp_broker':{'tools':['lookup']}},
                preflight_mcp=Mock(return_value={'status':'unavailable','authority':'controller host capability probe'})))
        report=check_workspace(ws,{})
        self.assertEqual(report['status'],'unavailable')
        ws.governance.preflight_mcp.assert_called_once()
        self.assertEqual(report['hosts']['controller_host']['authority'],'controller host capability probe')

    def test_failed_launcher_cannot_report_success(self):
        reply=subprocess.CompletedProcess([],1,'{"status":"ok"}','')
        with patch('keel.ipc.subprocess.run',return_value=reply):
            self.assertEqual(probe_async_stdio('python')['status'],'unavailable')

    def test_strict_blocks_before_model_and_preserves_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);repo=root/'repo';repo.mkdir();(repo/'app.py').write_text('x=1\n')
            model=Mock()
            config={'goal':'inspect','mode':'agent','acceptance':[[sys.executable,'-c','pass']], 'mcp_servers':SERVERS,'mcp_preflight':{}}
            with patch('keel.mcp_preflight.check_host',return_value={'status':'unavailable','checks':{}}):
                result=run(config,repo,root/'out',model=model)
            self.assertEqual(result['failure']['category'],'environment_blocked')
            self.assertEqual(result['budget']['model_calls'],0)
            model.complete.assert_not_called()
            self.assertEqual(json.loads((root/'out'/'mcp-preflight.json').read_text())['status'],'unavailable')

    def test_advisory_continues_explicit_work(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);repo=root/'repo';repo.mkdir();(repo/'app.py').write_text('x=1\n')
            config={'goal':'inspect','acceptance':[[sys.executable,'-c','pass']],'mcp_servers':SERVERS,
                    'mcp_preflight':{'mode':'advisory'}}
            with patch('keel.mcp_preflight.check_host',return_value={'status':'unavailable','checks':{}}):
                result=run(config,repo,root/'out')
            self.assertEqual(result['status'],'passed')
            self.assertEqual(result['mcp_preflight']['status'],'unavailable')
