from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.control_service import ControlService
from keel.core import PolicyDenied
from keel.governance import ControlStore, GovernanceUnavailable


class RunStoreContractTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.config={'path':str(Path(temp.name)/'control.sqlite'),'scope':'scope',
                     'max_tokens':100,'max_model_calls':10,'lease_seconds':10}
        self.clock=[100.0];self.store=ControlStore(self.config['path'],clock=lambda:self.clock[0])
        self.grant=self.store.runs.create(self.config,'run','fixture');self.runs=self.store.runs

    def bind(self):self.runs.bind_remote(self.grant,'worker','task','a'*64)

    def authorize(self,**changes):
        arguments=dict(run_id='run',principal='worker',task_id='task',scope='scope',grant_hash='a'*64,lease_seconds=10)
        return self.runs.authorize_remote(**{**arguments,**changes})

    def test_reopen_preserves_owner_and_rejects_foreign_scope_or_owner(self):
        reopened=ControlStore(self.config['path'],clock=lambda:self.clock[0])
        self.assertEqual(reopened.runs.get_bound(self.grant).identity,'fixture')
        for grant in (replace(self.grant,owner='foreign'),replace(self.grant,scope='foreign')):
            with self.assertRaises(PolicyDenied):reopened.runs.get_bound(grant)

    def test_remote_authorization_checks_principal_task_scope_and_grant(self):
        self.bind();self.assertEqual(self.authorize(),self.grant)
        for changed in ({'principal':'other'},{'task_id':'other'},{'scope':'other'},{'grant_hash':'b'*64}):
            with self.subTest(changed=changed),self.assertRaises(PolicyDenied):self.authorize(**changed)

    def test_remote_authorization_and_inspection_do_not_renew_lease(self):
        self.bind();self.clock[0]=105
        self.authorize();self.assertEqual(self.runs.get_bound(self.grant).deadline,110)
        self.assertEqual(self.runs.remote_task(self.grant),'task')
        self.assertEqual(self.runs.get_bound(self.grant).deadline,110)
        self.assertEqual(self.runs.require_active(self.grant).deadline,115)

    def test_expired_authorized_inspection_is_not_execution_permission(self):
        self.bind();self.clock[0]=111
        self.assertEqual(self.authorize(),self.grant)
        with self.assertRaises(PolicyDenied):self.runs.require_active(self.grant)

    def test_finish_preserves_unknown_holds_and_denies_more_execution(self):
        self.store.budgets.reserve(self.grant,40,request_id='request')
        self.runs.finish(self.grant,'failed')
        self.assertEqual(self.runs.get_bound(self.grant).status,'failed')
        with self.assertRaises(PolicyDenied):self.runs.require_active(self.grant)
        with self.store.transaction() as db:
            self.assertEqual(db.execute('SELECT status FROM governance_requests').fetchone()[0],'unknown')
            self.assertEqual(db.execute('SELECT held FROM governance_scopes').fetchone()[0],40)

    def test_reconcile_is_scope_filtered_and_does_not_authorize_replay(self):
        other=self.runs.create({**self.config,'scope':'other'},'other-run','fixture')
        self.clock[0]=111
        self.assertEqual(self.runs.reconcile_expired(scope='scope'),['run'])
        self.assertEqual(self.runs.get_bound(other).status,'running')
        with self.assertRaises(PolicyDenied):self.runs.require_active(other)

    def test_start_audit_failure_rolls_back_new_scope_and_run(self):
        with patch.object(self.store,'_event',side_effect=GovernanceUnavailable('fixture audit unavailable')):
            with self.assertRaises(GovernanceUnavailable):self.runs.create({**self.config,'scope':'new'},'new-run','fixture')
        with self.store.transaction() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM governance_scopes WHERE scope='new'").fetchone())
            self.assertIsNone(db.execute("SELECT 1 FROM governance_runs WHERE id='new-run'").fetchone())

    def test_finish_audit_failure_rolls_back_status_and_request_changes(self):
        self.store.budgets.reserve(self.grant,40,request_id='request');self.clock[0]=105
        with patch.object(self.store,'_event',side_effect=GovernanceUnavailable('fixture audit unavailable')):
            with self.assertRaises(GovernanceUnavailable):self.runs.finish(self.grant,'passed')
        state=self.runs.get_bound(self.grant)
        self.assertEqual((state.status,state.deadline),('running',110))
        with self.store.transaction() as db:
            self.assertEqual(db.execute('SELECT status FROM governance_requests').fetchone()[0],'dispatched')

    def test_expiry_audit_failure_does_not_partially_change_run(self):
        self.clock[0]=111
        with patch.object(self.store,'_event',side_effect=GovernanceUnavailable('fixture audit unavailable')):
            with self.assertRaises(GovernanceUnavailable):self.runs.reconcile_expired()
        self.assertEqual(self.runs.get_bound(self.grant).status,'running')
        with self.assertRaises(PolicyDenied):self.runs.require_active(self.grant)

    def test_existing_scope_policy_cannot_be_reset_by_new_run(self):
        with self.assertRaises(PolicyDenied):self.runs.create({**self.config,'max_tokens':200},'new-run','fixture')
        with self.store.transaction() as db:
            self.assertEqual(db.execute('SELECT max_tokens FROM governance_scopes').fetchone()[0],100)

    def test_remote_binding_survives_reopen(self):
        self.bind();self.runs=ControlStore(self.config['path'],clock=lambda:self.clock[0]).runs
        self.assertEqual(self.authorize(),self.grant)

    def test_begin_receipt_failure_rolls_back_run_binding_and_start_event(self):
        config={'path':self.config['path'],'scopes':{'scope':{'max_tokens':100,'max_model_calls':10,'lease_seconds':10}},
                'principals':[{'id':'worker','task_id':'task','scope':'scope','token_env':'KEEL_RUN_STORE_TEST','tools':{}}]}
        with patch.dict(os.environ,{'KEEL_RUN_STORE_TEST':'t'*48}):service=ControlService(config,clock=lambda:self.clock[0])
        with self.store.transaction() as db:
            db.execute("CREATE TRIGGER fail_begin_receipt BEFORE INSERT ON remote_operations WHEN NEW.operation_id='begin-fails' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(GovernanceUnavailable):
            service.operate('worker',{'operation_id':'begin-fails','action':'begin',
                'data':{'task_id':'task','identity':'fixture','wallclock_seconds':2}})
        with self.store.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM governance_runs').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM remote_run_bindings').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM governance_events').fetchone()[0],1)
