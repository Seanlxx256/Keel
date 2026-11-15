"""Controller MCP routing fixtures; no real server process is launched."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from keel.control_service import ControlService
from keel.core import PolicyDenied, digest
from keel.governance import GovernanceUnavailable
from keel.mcp_broker import RoutedMcpTools
from keel.mcp_client import McpTools


@unittest.skipUnless(importlib.util.find_spec('jsonschema'),'MCP broker schema fixtures require optional jsonschema')
class McpBrokerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        (self.repo/'a.py').write_text('value = 1\n',encoding='utf-8')
        self.alias='mcp__nav__find_symbol'
        self.config={'path':str(self.root/'control.sqlite'),
            'scopes':{'scope':{'max_tokens':1000,'max_model_calls':10,'lease_seconds':900}},
            'principals':[{'id':'worker','task_id':'task','scope':'scope','token_env':'KEEL_MCP_BROKER_TEST',
                           'require_mcp_broker':True,'tools':{'scout':[self.alias]}}],
            'read_broker':{'evidence_root':str(self.root/'evidence'),
                           'repositories':{'task':{'root':str(self.repo),'files':['a.py']}}},
            'mcp_broker':{'tasks':{'task':{'servers':{'nav':{'command':sys.executable,'args':['-m','fixture_only'],
                'timeout':2,'tools':{'find_symbol':{'roles':['scout'],'description':'Find a symbol by name',
                    'read_only':True,'input_schema':{'type':'object','properties':{'name':{'type':'string'}},
                                                     'required':['name'],'additionalProperties':False}}}}},
                'path_arguments':{self.alias:[]}}}}}
        env=patch.dict(os.environ,{'KEEL_MCP_BROKER_TEST':'t'*48});env.start();self.addCleanup(env.stop)
        self.service=ControlService(self.config)
        self.begin=self.service.operate('worker',{'operation_id':'begin','action':'begin',
            'data':{'task_id':'task','identity':'input','wallclock_seconds':100}})['result']
        self.run_id=self.begin['run_id']

    def request(self):
        return {'operation_id':'call','action':'mcp_call','run_id':self.run_id,
            'data':{'role':'scout','alias':self.alias,'arguments':{'name':'value'},'timeout':2,
                    'source_sha256':digest({'a.py':hashlib.sha256((self.repo/'a.py').read_bytes()).hexdigest()})}}

    @staticmethod
    def reply(tools,*args):
        tools.before_tool_call();tools.after_tool_result()
        tools.request_control.finish()
        return {'content':[{'type':'text','text':'symbol evidence'}]}

    def test_preflight_cached_without_mcp_dispatch(self):
        request={'operation_id':'preflight','action':'mcp_preflight','run_id':self.run_id,'data':{'timeout':2}}
        with patch('keel.mcp_preflight.check_host',return_value={'status':'unavailable','model_calls':0}) as probe,patch.object(McpTools,'call') as call:
            first=self.service.operate('worker',request)
            second=self.service.operate('worker',{**request,'operation_id':'second'})
        probe.assert_called_once();call.assert_not_called();self.assertEqual(first,second)
        self.assertEqual(first['result']['authority'],'controller host capability probe')

    def test_preflight_unknown_receipt_is_not_reexecuted(self):
        request={'operation_id':'preflight','action':'mcp_preflight','run_id':self.run_id,'data':{'timeout':2}}
        with patch('keel.mcp_preflight.check_host',return_value={'status':'ok'}) as probe:
            with patch('keel.mcp_broker.atomic_json',side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError):self.service.operate('worker',request)
            with self.assertRaises(GovernanceUnavailable):self.service.operate('worker',request)
        probe.assert_called_once()

    def test_preflight_rejects_changed_inputs_and_stopped_admission(self):
        request={'operation_id':'preflight','action':'mcp_preflight','run_id':self.run_id,'data':{'timeout':2}}
        self.service.mcp_broker.stopping.set()
        with self.assertRaises(GovernanceUnavailable):self.service.operate('worker',request)
        self.service.mcp_broker.stopping.clear()
        with patch('keel.mcp_preflight.check_host',return_value={'status':'ok'}):self.service.operate('worker',request)
        with self.assertRaises(PolicyDenied):self.service.operate('worker',{**request,'data':{'timeout':3}})

    def test_completed_duplicate_does_not_call_server_again(self):
        with patch.object(McpTools,'call',autospec=True,side_effect=self.reply) as call:
            first=self.service.operate('worker',self.request())
            second=self.service.operate('worker',self.request())
        call.assert_called_once();self.assertEqual(first,second)
        self.assertGreater(first['result']['artifact_bytes'],0)

    def test_invalid_arguments_are_rejected_before_server_invocation(self):
        request=self.request();request['data']['arguments']={'execute':'bad'}
        with patch.object(McpTools,'call') as call:
            with self.assertRaises(ValueError):self.service.operate('worker',request)
        call.assert_not_called()

    def test_wrong_role_is_denied(self):
        request=self.request();request['data']['role']='implementer'
        with self.assertRaises(PolicyDenied):self.service.operate('worker',request)

    def test_attempt_without_result_remains_unknown_and_is_not_replayed(self):
        def lost(tools,*args):tools.before_tool_call();raise TimeoutError('lost')
        with patch.object(McpTools,'call',autospec=True,side_effect=lost) as call:
            with self.assertRaises(GovernanceUnavailable):self.service.operate('worker',self.request())
            with self.assertRaises(GovernanceUnavailable):self.service.operate('worker',self.request())
        call.assert_called_once()

    def test_mutating_navigation_tool_is_not_certified_read_only(self):
        def mutation(tools,*args):
            tools.before_tool_call();(tools.ws.root/'a.py').write_text('value = 2\n')
            tools.after_tool_result();tools.request_control.finish();return {'content':[]}
        request=self.request()
        with patch.object(McpTools,'call',autospec=True,side_effect=mutation):
            with self.assertRaises(GovernanceUnavailable):self.service.operate('worker',request)
        self.assertEqual((self.repo/'a.py').read_text(),'value = 2\n')  # No unrequested rollback.

    def test_source_mismatch_is_a_known_preparation_rejection(self):
        request=self.request();request['data']['source_sha256']='0'*64
        result=self.service.operate('worker',request)
        self.assertFalse(result['ok']);self.assertEqual(result['error_type'],'PolicyDenied')

    def test_only_explicit_read_only_policy_is_accepted(self):
        self.config['mcp_broker']['tasks']['task']['servers']['nav']['tools']['find_symbol']['read_only']=False
        with self.assertRaises(ValueError):ControlService(self.config)

    def test_proxy_required_worker_cannot_configure_local_mcp(self):
        local=SimpleNamespace(servers={'nav':{}},catalog=lambda role:{})
        remote=SimpleNamespace(config={'mcp_broker':self.begin['mcp_broker']})
        with self.assertRaises(ValueError):RoutedMcpTools(local,SimpleNamespace(governance=remote))

    def test_direct_mcp_intent_is_not_controller_execution(self):
        result=self.service.operate('worker',{'operation_id':'direct','action':'tool_started','run_id':self.run_id,
            'data':{'role':'scout','tool':self.alias,'action_id':'direct'}})
        self.assertFalse(result['ok'])


if __name__=='__main__':unittest.main()
