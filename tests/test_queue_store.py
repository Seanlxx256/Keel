import concurrent.futures
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from keel.control_service import ControlService
from keel.core import PolicyDenied
from keel.governance import ControlStore, GovernanceUnavailable
from keel.queue_store import SqliteQueueStore
from keel.task_queue import TaskQueue


class QueueStoreContractTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'control.sqlite';self.now=1000
        self.store=ControlStore(self.path,clock=lambda:self.now)
        self.backend=SqliteQueueStore(self.store)
        self.backend.enqueue('item','worker','task',{'source_sha256':'a'*64})

    def claim(self,run='run'):
        return self.backend.claim('worker','task',run,self.now+1000)

    def test_concurrent_consumers_claim_one_task_only_once(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            claims=list(pool.map(lambda index:self.claim('run-'+str(index)),range(8)))
        self.assertEqual(sum(value['task'] is not None for value in claims),1)
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM control_task_events WHERE kind='claimed'").fetchone()[0],1)

    def test_queue_audit_failure_rolls_back_claim_and_fence(self):
        with patch.object(self.backend,'_event',side_effect=GovernanceUnavailable('fixture unavailable')):
            with self.assertRaises(GovernanceUnavailable):self.claim()
        state=self.backend.status('worker','task','item')
        self.assertEqual((state['status'],state['fence']),( 'queued',0))

    def test_queue_audit_failure_rolls_back_enqueue(self):
        with patch.object(self.backend,'_event',side_effect=GovernanceUnavailable('fixture unavailable')):
            with self.assertRaises(GovernanceUnavailable):self.backend.enqueue('new','worker','task',{})
        with self.assertRaises(PolicyDenied):self.backend.status('worker','task','new')

    def test_reopen_preserves_ownership_and_denies_foreign_identity(self):
        self.claim()
        reopened=SqliteQueueStore(ControlStore(self.path,clock=lambda:self.now))
        self.assertEqual(reopened.status('worker','task','item')['run_id'],'run')
        with self.assertRaises(PolicyDenied):reopened.status('foreign','task','item')
        self.assertIsNone(reopened.claim('foreign','task','foreign-run',self.now+100)['task'])

    def test_expired_work_needs_operator_requeue_and_old_fence_cannot_finish(self):
        self.claim();self.backend.transition('worker','task','run','item',1,'start')
        self.now+=301
        self.assertIsNone(self.claim('new-run')['task'])
        self.assertEqual(self.backend.status('worker','task','item')['status'],'unknown')
        self.backend.requeue('item',1,'operator verified no remaining external effect')
        self.assertEqual(self.claim('new-run')['task']['fence'],2)
        with self.assertRaises(PolicyDenied):
            self.backend.transition('worker','task','run','item',1,'finish',{'status':'passed','artifact_sha256':'b'*64})

    def test_same_run_cannot_accumulate_two_active_claims(self):
        self.backend.enqueue('second','worker','task',{})
        self.claim()
        with self.assertRaises(PolicyDenied):self.claim()

    def test_existing_facade_uses_backend_without_sql_callbacks(self):
        backend=Mock();backend.claim.return_value={'task':None}
        backend.transaction_domain=self.store.transaction_domain
        facade=TaskQueue(self.store,backend=backend)
        self.assertEqual(facade.claim('worker','task','run',1200),{'task':None})
        backend.claim.assert_called_once_with('worker','task','run',1200)
        self.assertIsInstance(TaskQueue(self.store).backend,SqliteQueueStore)

    def test_controller_receipt_failure_rolls_back_claim_and_queue_audit(self):
        config={'path':str(self.path),'scopes':{'scope':{'max_tokens':100,'max_model_calls':10,'lease_seconds':1000}},
                'principals':[{'id':'worker','task_id':'task','scope':'scope','token_env':'KEEL_QUEUE_STORE_TEST','tools':{}}]}
        with patch.dict(os.environ,{'KEEL_QUEUE_STORE_TEST':'t'*48}):
            service=ControlService(config,clock=lambda:self.now)
        run=service.operate('worker',{'operation_id':'begin','action':'begin','data':{'task_id':'task','identity':'fixture','wallclock_seconds':100}})['result']['run_id']
        with self.store.transaction() as db:
            db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON remote_operations WHEN NEW.operation_id='claim-fails' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(GovernanceUnavailable):
            service.operate('worker',{'operation_id':'claim-fails','action':'queue_claim','run_id':run,'data':{}})
        state=service.queue.status('worker','task','item')
        self.assertEqual((state['status'],state['fence']),('queued',0))
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM control_task_events WHERE kind='claimed'").fetchone()[0],0)
