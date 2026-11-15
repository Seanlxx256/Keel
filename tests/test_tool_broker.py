"""Controller read execution and Runtime evidence import contracts."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.control_service import ControlService
from keel.core import Budget, Ledger, Limits, PolicyDenied, Trace
from keel.gateway import ToolGateway
from keel.remote_governance import RemoteSession
from keel.workspace import Workspace


class ToolBrokerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        (self.repo/'a.py').write_text('value = 1\n',encoding='utf-8')
        (self.repo/'secret.txt').write_text('not catalogued',encoding='utf-8')
        self.config={'path':str(self.root/'control.sqlite'),
            'scopes':{'scope':{'max_tokens':1000,'max_model_calls':10,'lease_seconds':900}},
            'principals':[{'id':'worker','task_id':'task','scope':'scope','token_env':'KEEL_BROKER_TEST',
                           'require_read_broker':True,'tools':{'scout':['read_file','read_page','read_lines','search_code','list_files']}}],
            'read_broker':{'evidence_root':str(self.root/'controller-evidence'),
                           'repositories':{'task':{'root':str(self.repo),'files':['a.py']}}}}
        env=patch.dict(os.environ,{'KEEL_BROKER_TEST':'t'*48});env.start();self.addCleanup(env.stop)
        self.service=ControlService(self.config)
        self.begin=self.service.operate('worker',{'operation_id':'begin','action':'begin',
            'data':{'task_id':'task','identity':'input','wallclock_seconds':100}})['result']
        self.run_id=self.begin['run_id']

    def request(self,tool='read_file',args=None,operation='read',role='scout'):
        return {'operation_id':operation,'action':'tool_read','run_id':self.run_id,
                'data':{'role':role,'tool':tool,'args':args if args is not None else {'path':'a.py'}}}

    def test_controller_read_has_raw_source_hash_and_replay_is_historical(self):
        broker=self.service.read_broker
        with patch.object(broker,'_observe',wraps=broker._observe) as observe:
            first=self.service.operate('worker',self.request())
            second=self.service.operate('worker',self.request())
        observe.assert_called_once()
        self.assertEqual(first['result']['payload']['text'],(self.repo/'a.py').read_bytes().decode('utf-8'))
        self.assertEqual(first['result']['source_hashes']['a.py'],hashlib.sha256((self.repo/'a.py').read_bytes()).hexdigest())
        self.assertTrue(second['result']['historical_response'])

    def test_unapproved_file_and_path_escape_are_denied(self):
        for number,path in enumerate(['secret.txt','../control.sqlite',str(self.root/'control.sqlite')]):
            result=self.service.operate('worker',self.request(args={'path':path},operation=str(number)))
            self.assertFalse(result['ok']);self.assertEqual(result['error_type'],'PolicyDenied')

    def test_explicit_utf8_crlf_is_preserved_and_hashed_by_bytes(self):
        raw='name = "测试"\r\nvalue = 1\r\n'.encode('utf-8')
        (self.repo/'a.py').write_bytes(raw)
        result=self.service.operate('worker',self.request())['result']
        self.assertEqual(result['payload']['text'],raw.decode('utf-8'))
        self.assertEqual(result['source_hashes']['a.py'],hashlib.sha256(raw).hexdigest())

    def test_role_and_non_read_tool_are_denied(self):
        with self.assertRaises(PolicyDenied):self.service.operate('worker',self.request(role='implementer'))
        with self.assertRaises(PolicyDenied):self.service.operate('worker',self.request(tool='replace'))

    def test_direct_local_read_intent_cannot_substitute_for_broker_execution(self):
        result=self.service.operate('worker',{'operation_id':'direct','action':'tool_started','run_id':self.run_id,
            'data':{'role':'scout','tool':'read_file','action_id':'a'}})
        self.assertFalse(result['ok']);self.assertEqual(result['error_type'],'PolicyDenied')

    def test_list_and_search_only_approved_files(self):
        listed=self.service.operate('worker',self.request('list_files',{},'list'))
        self.assertEqual(listed['result']['payload']['files'],['a.py'])
        result=self.service.operate('worker',self.request('search_code',{'query':'not catalogued'},'search'))
        self.assertEqual(result['result']['payload']['matches'],[])

    def test_changed_operation_input_is_rejected(self):
        self.service.operate('worker',self.request())
        with self.assertRaises(PolicyDenied):self.service.operate('worker',self.request(tool='read_page',args={'path':'a.py','start_line':1}))

    def gateway(self,repo):
        remote=RemoteSession({'endpoint':'http://127.0.0.1:8788','token_env':'KEEL_BROKER_TEST','task_id':'task'})
        remote.run_id=self.run_id
        remote.config={'scope':'scope','lease_seconds':900,'read_broker':self.begin['read_broker']}
        def send(request):
            value=self.service.operate('worker',request)
            if not value['ok']:raise PolicyDenied('Rejected')
            return value['result']
        remote._send=send
        ledger=Ledger(self.root/('worker-'+str(len(list(self.root.glob('worker-*.sqlite'))))+'.sqlite'))
        self.addCleanup(ledger.close)
        ws=Workspace(repo,Budget(Limits()),ledger,Trace(self.root/'worker-trace.jsonl'))
        ws.governance=remote
        return ToolGateway('scout',ws),remote

    def test_gateway_imports_local_fact_and_does_not_request_local_execution(self):
        gateway,remote=self.gateway(self.repo)
        with patch.object(remote,'tool_started') as local:
            result=gateway.call('read_file',{'path':'a.py'})
        local.assert_not_called()
        payload=gateway.ws.ledger.recall(result['fact_id'])
        self.assertEqual(payload['authority'],'controller executed read observation')
        self.assertEqual(gateway.read_evidence[result['fact_id']]['path'],'a.py')

    def test_gateway_rejects_source_drift_before_evidence_import(self):
        worker=self.root/'other-workspace';worker.mkdir()
        (worker/'a.py').write_text('value = 2\n',encoding='utf-8')
        gateway,_=self.gateway(worker)
        with self.assertRaises(PolicyDenied):gateway.call('read_file',{'path':'a.py'})
        self.assertEqual(gateway.visible_facts,set())

    def test_metadata_catalog_is_rejected_on_server(self):
        (self.repo/'.git').mkdir();(self.repo/'.git'/'config').write_text('private',encoding='utf-8')
        self.config['read_broker']['repositories']['task']['files']=['.git/config']
        with self.assertRaises(PolicyDenied):ControlService(self.config)


if __name__=='__main__':unittest.main()
