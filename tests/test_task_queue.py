"""Controller queue contracts; supplied separately from live sandbox validation."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.control_service import ControlService
from keel.core import PolicyDenied
from keel.governance import ControlStore
from keel.task_queue import TaskQueue


class TaskQueueTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'control.sqlite';self.now=1000
        self.store=ControlStore(self.path,clock=lambda:self.now)
        self.queue=TaskQueue(self.store)
        self.queue.enqueue('item','worker','task',{'input_sha256':'a'*64})

    def claim(self,run='run'):
        return self.queue.claim('worker','task',run,self.now+1000)['task']

    def test_enqueue_idempotence_rejects_changed_input(self):
        self.assertTrue(self.queue.enqueue('item','worker','task',{'input_sha256':'a'*64})['reused'])
        with self.assertRaises(PolicyDenied):self.queue.enqueue('item','worker','task',{'changed':True})

    def test_only_one_run_can_claim_an_item(self):
        self.assertEqual(self.claim()['fence'],1)
        self.assertIsNone(self.claim('other'))

    def test_expired_claim_is_unknown_not_queued_and_old_fence_is_rejected(self):
        item=self.claim();self.now+=301
        self.assertIsNone(self.claim('other'))
        self.assertEqual(self.queue.status('worker','task','item')['status'],'unknown')
        self.queue.requeue('item',item['fence'],'inspected external effects; safe to retry')
        new=self.claim('new');self.assertEqual(new['fence'],2)
        with self.assertRaises(PolicyDenied):
            self.queue.transition('worker','task','run','item',1,'start')

    def test_expired_running_task_cannot_be_renewed(self):
        self.claim();self.queue.transition('worker','task','run','item',1,'start')
        self.now+=301
        with self.assertRaises(PolicyDenied):self.queue.renew('worker','task','run','item',1,self.now+100)

    def test_result_is_worker_report_not_independent_success(self):
        self.claim();self.queue.transition('worker','task','run','item',1,'start')
        result=self.queue.transition('worker','task','run','item',1,'finish',
                                     {'status':'passed','artifact_sha256':'b'*64})
        self.assertEqual(result['status'],'reported_passed')
        with self.assertRaises(PolicyDenied):self.queue.requeue('item',1,'repeat success')

    def test_reopen_preserves_claim_and_rejects_wrong_principal(self):
        self.claim()
        reopened=TaskQueue(ControlStore(self.path,clock=lambda:self.now))
        self.assertEqual(reopened.status('worker','task','item')['fence'],1)
        with self.assertRaises(PolicyDenied):reopened.status('other','task','item')

    def test_service_replayed_claim_cannot_authorize_dispatch(self):
        config={'path':str(self.path),'scopes':{'scope':{'max_tokens':1000,'max_model_calls':10,'lease_seconds':1000}},
                'principals':[{'id':'worker','task_id':'task','scope':'scope',
                               'token_env':'KEEL_QUEUE_TEST_TOKEN','tools':{}}]}
        with patch.dict(os.environ,{'KEEL_QUEUE_TEST_TOKEN':'t'*48}):
            service=ControlService(config,clock=lambda:self.now)
        begin=service.operate('worker',{'operation_id':'begin','action':'begin',
            'data':{'task_id':'task','identity':'input','wallclock_seconds':100}})
        request={'operation_id':'claim','action':'queue_claim','run_id':begin['result']['run_id'],'data':{}}
        first=service.operate('worker',request);replay=service.operate('worker',request)
        self.assertTrue(first['result']['dispatch_allowed'])
        self.assertFalse(replay['result']['dispatch_allowed'])
        self.assertEqual(first['result']['task']['fence'],replay['result']['task']['fence'])


if __name__=='__main__':unittest.main()
