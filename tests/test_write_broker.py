"""Replacement authorization and uncertain-effect contracts; no providers."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.control_service import ControlService
from keel.core import Budget, Ledger, Limits, PolicyDenied, Trace
from keel.governance import GovernanceUnavailable
from keel.remote_governance import RemoteSession
from keel.workspace import Workspace
from keel.write_broker import WriteWorkspace


class WriteBrokerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.file=self.repo/'a.py';self.file.write_text('value = 1\n',encoding='utf-8')
        (self.repo/'b.py').write_text('other = 1\n',encoding='utf-8')
        self.config={'path':str(self.root/'control.sqlite'),
            'scopes':{'scope':{'max_tokens':1000,'max_model_calls':10,'lease_seconds':900}},
            'principals':[{'id':'worker','task_id':'task','scope':'scope','token_env':'KEEL_WRITE_TEST',
                           'require_write_broker':True,'tools':{'implementer':['replace']}}],
            'read_broker':{'evidence_root':str(self.root/'evidence'),
                           'repositories':{'task':{'root':str(self.repo),'files':['a.py','b.py'],'writable_files':['a.py']}}}}
        env=patch.dict(os.environ,{'KEEL_WRITE_TEST':'t'*48});env.start();self.addCleanup(env.stop)
        self.service=ControlService(self.config)
        self.begin=self.service.operate('worker',{'operation_id':'begin','action':'begin',
            'data':{'task_id':'task','identity':'input','wallclock_seconds':100}})['result']
        self.run_id=self.begin['run_id'];self.before=hashlib.sha256(self.file.read_bytes()).hexdigest()

    def request(self,op='write',**overrides):
        data={'path':'a.py','old':'value = 1','new':'value = 2','before_sha256':self.before}
        data.update(overrides)
        return {'operation_id':op,'action':'tool_replace','run_id':self.run_id,'data':data}

    def test_replacement_is_executed_once_and_receipt_is_cached(self):
        with patch.object(WriteWorkspace,'_write_replacement',autospec=True,
                          side_effect=WriteWorkspace._write_replacement) as write:
            first=self.service.operate('worker',self.request())
            replay=self.service.operate('worker',self.request())
        write.assert_called_once();self.assertTrue(first['ok'])
        self.assertEqual(self.file.read_text(),'value = 2\n')
        self.assertTrue(replay['result']['historical_response'])

    def test_stale_hash_does_not_write(self):
        with self.assertRaises(PolicyDenied):self.service.operate('worker',self.request(before_sha256='0'*64))
        self.assertEqual(self.file.read_text(),'value = 1\n')

    def test_readable_file_is_not_automatically_writable(self):
        with self.assertRaises(PolicyDenied):self.service.operate('worker',self.request(path='b.py'))

    def test_invalid_python_is_rejected_before_effect(self):
        result=self.service.operate('worker',self.request(new='value = ('))
        self.assertFalse(result['ok']);self.assertEqual(self.file.read_text(),'value = 1\n')

    def test_write_then_reporting_failure_remains_unknown_and_blocks_next_write(self):
        original=WriteWorkspace._write_replacement
        def fail_after_write(ws,path,raw):
            original(ws,path,raw)
            raise OSError('simulated completion loss')
        with patch.object(WriteWorkspace,'_write_replacement',fail_after_write):
            with self.assertRaises(GovernanceUnavailable):self.service.operate('worker',self.request())
        self.assertEqual(self.file.read_text(),'value = 2\n')
        with self.assertRaises(GovernanceUnavailable):self.service.operate('worker',self.request())
        with self.assertRaises(PolicyDenied):
            self.service.operate('worker',self.request(op='next',old='value = 2',new='value = 3',
                before_sha256=hashlib.sha256(self.file.read_bytes()).hexdigest()))
        self.assertEqual(self.service.write_broker.inspect('worker',self.run_id,'write')['status'],'inflight')

    def test_protected_test_cannot_enter_write_catalog(self):
        folder=self.repo/'tests';folder.mkdir();(folder/'test_a.py').write_text('assert True\n')
        spec=self.config['read_broker']['repositories']['task']
        spec['files'].append('tests/test_a.py');spec['writable_files']=['tests/test_a.py']
        with self.assertRaises(PolicyDenied):ControlService(self.config)

    def test_worker_workspace_routes_replace_without_duplicate_local_write(self):
        remote=RemoteSession({'endpoint':'http://127.0.0.1:8788','token_env':'KEEL_WRITE_TEST','task_id':'task'})
        remote.run_id=self.run_id;remote.config={'write_broker':self.begin['write_broker']}
        remote._send=lambda request:self.service.operate('worker',request)['result']
        ledger=Ledger(self.root/'local.sqlite');self.addCleanup(ledger.close)
        ws=Workspace(self.repo,Budget(Limits()),ledger,Trace(self.root/'local.jsonl'));ws.governance=remote
        with patch.object(ws,'_write_replacement') as local_write:
            ws.replace('a.py','value = 1','value = 2')
        local_write.assert_not_called();self.assertEqual(self.file.read_text(),'value = 2\n')

    def test_direct_intent_cannot_substitute_for_write_broker(self):
        result=self.service.operate('worker',{'operation_id':'direct','action':'tool_started','run_id':self.run_id,
            'data':{'role':'implementer','tool':'replace','action_id':'direct'}})
        self.assertFalse(result['ok'])

    def test_pending_write_inspection_preserves_original_operation(self):
        remote=RemoteSession({'endpoint':'http://127.0.0.1:8788','token_env':'KEEL_WRITE_TEST','task_id':'task'})
        remote.pending=self.request()
        original=remote.pending.copy()
        with patch.object(remote,'_send',return_value={'status':'inflight'}) as send:
            self.assertEqual(remote.inspect_pending_write()['status'],'inflight')
        self.assertEqual(remote.pending,original)
        self.assertEqual(send.call_args.args[0]['action'],'tool_write_status')


if __name__=='__main__':unittest.main()
