import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from keel.control_service import ControlService
from keel.governance import ControlStore, GovernanceUnavailable
from keel.operation_store import SqliteOperationStore
from keel.queue_store import SqliteQueueStore
from keel.task_queue import TaskQueue
from keel.transaction_domain import require_shared_domain


class TransactionDomainTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.config={'path':str(Path(temp.name)/'control.sqlite'),'scope':'scope',
                     'max_tokens':100,'max_model_calls':10,'lease_seconds':10}
        self.store=ControlStore(self.config['path']);self.session=self.store.begin(self.config,'run','fixture')
        self.other=ControlStore(self.config['path'])

    def test_default_repositories_share_one_nested_transaction(self):
        operations=SqliteOperationStore(self.store);queue=TaskQueue(self.store)
        require_shared_domain(self.store,budget=self.store.budgets,runs=self.store.runs,operations=operations,queue=queue)
        with self.store.transaction() as outer:
            with self.store.transaction() as inner:self.assertIs(outer,inner)

    def test_same_path_is_not_the_same_transaction_context(self):
        self.assertEqual(self.store.path,self.other.path)
        with self.assertRaises(GovernanceUnavailable):require_shared_domain(self.store,budget=self.other.budgets)

    def test_missing_domain_is_rejected(self):
        with self.assertRaises(GovernanceUnavailable):require_shared_domain(self.store,budget=SimpleNamespace())

    def test_domain_property_exception_does_not_leak_raw_message(self):
        class Broken:
            @property
            def transaction_domain(self):raise RuntimeError('secret credentials')
        with self.assertRaises(GovernanceUnavailable) as caught:require_shared_domain(self.store,budget=Broken())
        self.assertNotIn('secret',str(caught.exception))

    def test_session_rejects_mixed_budget_before_backend_execution(self):
        self.store.budgets=self.other.budgets
        with patch.object(self.other.budgets,'reserve') as reserve:
            with self.assertRaises(GovernanceUnavailable):self.session.reserve(10)
        reserve.assert_not_called()
        self.assertEqual(self.other.inspect(scope='scope')['scope']['held'],0)

    def test_begin_rejects_mixed_run_store_before_backend_execution(self):
        self.store.runs=self.other.runs
        with patch.object(self.other.runs,'create') as create:
            with self.assertRaises(GovernanceUnavailable):self.store.begin(self.config,'new','fixture')
        create.assert_not_called()

    def test_finish_rejects_mixed_run_store_before_backend_execution(self):
        self.store.runs=self.other.runs
        with patch.object(self.other.runs,'finish') as finish:
            with self.assertRaises(GovernanceUnavailable):self.session.finish('passed')
        finish.assert_not_called()

    def test_queue_constructor_rejects_foreign_backend(self):
        foreign=SqliteQueueStore(self.other)
        with self.assertRaises(GovernanceUnavailable):TaskQueue(self.store,backend=foreign)

    def test_queue_backend_replacement_is_checked_before_dispatch(self):
        queue=TaskQueue(self.store);queue.backend=SqliteQueueStore(self.other)
        with patch.object(queue.backend,'claim') as claim:
            with self.assertRaises(GovernanceUnavailable):queue.claim('worker','task','run',9999999999)
        claim.assert_not_called()

    def test_control_receipt_backend_mismatch_blocks_business_handler(self):
        config={'path':self.config['path'],'scopes':{'scope':{'max_tokens':100,'max_model_calls':10,'lease_seconds':10}},
                'principals':[{'id':'worker','scope':'scope','task_id':'task','token_env':'KEEL_DOMAIN_TEST','tools':{}}]}
        with patch.dict(os.environ,{'KEEL_DOMAIN_TEST':'t'*48}):service=ControlService(config)
        service.operations=SqliteOperationStore(self.other)
        with patch.object(service,'_execute') as execute:
            with self.assertRaises(GovernanceUnavailable):service.operate('worker',{'operation_id':'begin','action':'begin',
                'data':{'task_id':'task','identity':'fixture','wallclock_seconds':2}})
        execute.assert_not_called()
