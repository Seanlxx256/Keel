"""Fixed acceptance protocol fixtures; no live Docker or paid providers."""
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.control_service import ControlService
from keel.core import PolicyDenied, digest
from keel.remote_governance import RemoteSession


class ExecutionBrokerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);repo=self.root/'repo';repo.mkdir()
        (repo/'a.py').write_text('value = 1\n',encoding='utf-8')
        self.acceptance=[{'command':['python','-m','pytest','--junitxml={junit}'],'junit':True}]
        self.config={'path':str(self.root/'control.sqlite'),
            'scopes':{'scope':{'max_tokens':1000,'max_model_calls':10,'lease_seconds':900}},
            'principals':[{'id':'worker','task_id':'task','scope':'scope','token_env':'KEEL_EXECUTION_TEST',
                           'require_execution_broker':True,'tools':{'verifier':['verify']}}],
            'read_broker':{'evidence_root':str(self.root/'evidence'),
                           'repositories':{'task':{'root':str(repo),'files':['a.py']}}},
            'execution_broker':{'tasks':{'task':{'execution':{'backend':'docker','image':'sha256:'+'a'*64},
                                                'acceptance':self.acceptance,'max_seconds':120}}}}
        env=patch.dict(os.environ,{'KEEL_EXECUTION_TEST':'t'*48});env.start();self.addCleanup(env.stop)
        self.service=ControlService(self.config)
        self.run_id=self.service.operate('worker',{'operation_id':'begin','action':'begin',
            'data':{'task_id':'task','identity':'input','wallclock_seconds':200}})['result']['run_id']

    def request(self):
        return {'operation_id':'start','action':'verify_start','run_id':self.run_id,
                'data':{'source_sha256':'b'*64,'acceptance_sha256':digest(self.acceptance),'timeout':100}}

    def test_duplicate_start_does_not_launch_second_executor(self):
        with patch('keel.execution_broker.threading.Thread.start') as start:
            first=self.service.operate('worker',self.request())
            second=self.service.operate('worker',self.request())
        start.assert_called_once();self.assertEqual(first['result']['job_id'],second['result']['job_id'])
        self.assertTrue(second['result']['historical_response'])

    def test_client_cannot_replace_fixed_acceptance(self):
        request=self.request();request['data']['acceptance_sha256']='0'*64
        with patch('keel.execution_broker.threading.Thread.start') as start:
            with self.assertRaises(PolicyDenied):self.service.operate('worker',request)
        start.assert_not_called()

    def test_extra_command_field_is_rejected(self):
        request=self.request();request['data']['command']=['anything']
        with self.assertRaises(ValueError):self.service.operate('worker',request)

    def test_restart_does_not_treat_unobserved_job_as_running_or_relaunch_it(self):
        with patch('keel.execution_broker.threading.Thread.start'):
            job=self.service.operate('worker',self.request())['result']['job_id']
        restarted=ControlService(self.config)
        result=restarted.operate('worker',{'operation_id':'status','action':'verify_status','run_id':self.run_id,
                                          'data':{'job_id':job}})
        self.assertEqual(result['result']['status'],'unknown')

    def test_local_or_mutable_image_configuration_is_rejected(self):
        for execution in [{'backend':'local'},{'backend':'docker','image':'python:latest'}]:
            self.config['execution_broker']['tasks']['task']['execution']=execution
            with self.assertRaises(ValueError):ControlService(self.config)

    def test_worker_cannot_claim_verification_outcome_instead_of_executing(self):
        result=self.service.operate('worker',{'operation_id':'fake','action':'event','run_id':self.run_id,
            'data':{'kind':'verification_outcome','payload':{'returncode':0},'action_id':'fake'}})
        self.assertFalse(result['ok'])

    def test_client_collects_complete_paged_result_with_hash_binding(self):
        session=RemoteSession({'endpoint':'http://127.0.0.1:8788','token_env':'KEEL_EXECUTION_TEST','task_id':'task'})
        session.run_id=self.run_id
        payload={'authority':'controller executed fixed Docker acceptance','source_sha256':'b'*64,
                 'acceptance_sha256':'c'*64,'verification':[{'stdout':'x'*70000}],'job_id':'d'*32}
        raw=json.dumps(payload).encode()
        def rpc(action,data):
            if action=='verify_start':return {'job_id':'d'*32}
            if action=='verify_status':return {'status':'complete','receipt':{'result_bytes':len(raw),
                'result_sha256':hashlib.sha256(raw).hexdigest()}}
            offset=data['offset'];chunk=raw[offset:offset+65536]
            return {'data_base64':base64.b64encode(chunk).decode(),
                    'next_offset':offset+len(chunk) if offset+len(chunk)<len(raw) else None}
        with patch.object(session,'_rpc',side_effect=rpc):
            self.assertEqual(session.verify_commands('b'*64,'c'*64,10),payload)


if __name__=='__main__':unittest.main()
