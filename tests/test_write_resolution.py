"""Trusted adjudication contracts. No Docker, provider or network calls."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.control_service import ControlService
from keel.core import PolicyDenied
from keel.governance import GovernanceUnavailable
from keel.write_broker import WriteWorkspace


class WriteResolutionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);repo=self.root/'repo';repo.mkdir()
        self.file=repo/'a.py';self.file.write_text('value = 1\n',encoding='utf-8')
        config={'path':str(self.root/'control.sqlite'),
            'scopes':{'scope':{'max_tokens':1000,'max_model_calls':10,'lease_seconds':900}},
            'principals':[{'id':'worker','task_id':'task','scope':'scope','token_env':'KEEL_RESOLUTION_TEST',
                           'tools':{'implementer':['replace']}}],
            'read_broker':{'evidence_root':str(self.root/'evidence'),
                'repositories':{'task':{'root':str(repo),'files':['a.py'],'writable_files':['a.py']}}}}
        env=patch.dict(os.environ,{'KEEL_RESOLUTION_TEST':'t'*48});env.start();self.addCleanup(env.stop)
        self.service=ControlService(config);self.broker=self.service.write_broker
        self.run_id=self.service.operate('worker',{'operation_id':'begin','action':'begin',
            'data':{'task_id':'task','identity':'input','wallclock_seconds':100}})['result']['run_id']
        self.request={'operation_id':'write','action':'tool_replace','run_id':self.run_id,
            'data':{'path':'a.py','old':'value = 1','new':'value = 2',
                    'before_sha256':hashlib.sha256(self.file.read_bytes()).hexdigest()}}

    def uncertain(self,applied=True):
        original=WriteWorkspace._write_replacement
        def interrupted(ws,path,raw):
            if applied:original(ws,path,raw)
            else:ws.effect_attempted=True
            raise OSError('simulated effect/ack uncertainty')
        with patch.object(WriteWorkspace,'_write_replacement',interrupted):
            with self.assertRaises(GovernanceUnavailable):self.service.operate('worker',self.request)
        return self.broker.resolution_plan('worker',self.run_id,'write')

    def resolve(self,plan,decision='applied'):
        return self.broker.resolve(plan,decision=decision,operator='operator',reason='inspected original worker and source',quiesced=True)

    def test_applied_resolution_revokes_run_without_rewriting_source(self):
        plan=self.uncertain()
        with patch.object(WriteWorkspace,'_write_replacement') as write:
            result=self.resolve(plan)
        write.assert_not_called();self.assertTrue(result['original_run_revoked'])
        self.assertEqual(self.file.read_text(),'value = 2\n')
        replay=self.service.operate('worker',self.request)
        self.assertFalse(replay['ok']);self.assertEqual(replay['error_type'],'PolicyDenied')

    def test_no_effect_requires_before_hash(self):
        plan=self.uncertain(applied=False)
        self.assertEqual(self.resolve(plan,'no_effect')['decision'],'no_effect')
        self.assertEqual(self.file.read_text(),'value = 1\n')

    def test_conflicting_decision_does_not_unlock(self):
        plan=self.uncertain()
        with self.assertRaises(PolicyDenied):self.resolve(plan,'no_effect')
        self.assertEqual(self.broker.inspect('worker',self.run_id,'write')['status'],'inflight')

    def test_source_change_since_preview_keeps_write_unresolved(self):
        plan=self.uncertain();self.file.write_text('value = 3\n')
        with self.assertRaises(PolicyDenied):self.resolve(plan)
        self.assertEqual(self.broker.inspect('worker',self.run_id,'write')['status'],'inflight')

    def test_exact_adjudication_retry_is_idempotent_but_changed_reason_denied(self):
        plan=self.uncertain();self.resolve(plan)
        self.assertTrue(self.resolve(plan)['historical_response'])
        with self.assertRaises(PolicyDenied):
            self.broker.resolve(plan,decision='applied',operator='operator',reason='changed',quiesced=True)

    def test_active_path_lock_blocks_adjudication(self):
        plan=self.uncertain()
        with self.broker._path_lock(self.file):
            with self.assertRaises(GovernanceUnavailable):self.resolve(plan)

    def test_quiescence_acknowledgement_and_request_identity_required(self):
        plan=self.uncertain()
        with self.assertRaises(ValueError):
            self.broker.resolve(plan,decision='applied',operator='operator',reason='inspected')
        plan['request_hash']='0'*64
        with self.assertRaises(PolicyDenied):self.resolve(plan)

    def test_worker_rpc_cannot_adjudicate_its_own_write(self):
        plan=self.uncertain()
        response=self.service.operate('worker',{'operation_id':'pretend-admin','action':'resolve_write',
            'run_id':self.run_id,'data':{'plan':plan,'decision':'applied'}})
        self.assertFalse(response['ok'])
        self.assertEqual(self.broker.inspect('worker',self.run_id,'write')['status'],'inflight')


if __name__=='__main__':unittest.main()
