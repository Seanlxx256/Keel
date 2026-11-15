from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from keel.budget_store import SqliteBudgetStore
from keel.core import PolicyDenied
from keel.governance import ControlStore, GovernanceUnavailable


class BudgetStoreContractTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.config={'path':str(Path(temp.name)/'control.sqlite'),'scope':'scope','max_tokens':100,'max_model_calls':10,'lease_seconds':10}
        self.clock=[100.0]
        self.store=ControlStore(self.config['path'],clock=lambda:self.clock[0])
        self.session=self.store.begin(self.config,'run','fixture')
        self.backend=self.store.budgets;self.grant=self.session._budget_grant()

    def test_duplicate_reservation_is_not_permission_to_repeat(self):
        self.backend.reserve(self.grant,40,request_id='request')
        with self.assertRaises(PolicyDenied):self.backend.reserve(self.grant,40,request_id='request')
        self.assertEqual(self.session.report()['reserved_or_unknown_tokens'],40)
        self.assertEqual(self.session.report()['model_calls'],1)

    def test_known_settlement_is_idempotent_and_conflicting_usage_denied(self):
        self.backend.reserve(self.grant,40,request_id='request')
        self.backend.settle(self.grant,'request',10)
        self.backend.settle(self.grant,'request',10)
        with self.assertRaises(PolicyDenied):self.backend.settle(self.grant,'request',11)
        self.assertEqual(self.session.report()['spent_tokens'],10)
        outcomes=[event for event in self.store.events('run') if event['kind']=='model_outcome']
        self.assertEqual(len(outcomes),1)

    def test_unknown_survives_backend_reopen_and_late_known_accounting(self):
        self.backend.reserve(self.grant,40,request_id='request')
        self.backend.settle(self.grant,'request',None)
        reopened=SqliteBudgetStore(ControlStore(self.config['path'],clock=lambda:self.clock[0]))
        self.assertEqual(self.session.report()['reserved_or_unknown_tokens'],40)
        reopened.settle(self.grant,'request',7)
        self.assertEqual(self.session.report()['reserved_or_unknown_tokens'],0)
        self.assertEqual(self.session.report()['spent_tokens'],7)

    def test_late_settlement_does_not_reactivate_expired_run(self):
        self.backend.reserve(self.grant,40,request_id='request');self.clock[0]=111
        self.store.reconcile_expired()
        self.backend.settle(self.grant,'request',7)
        self.assertEqual(self.session.report()['status'],'unreachable')
        with self.assertRaises(PolicyDenied):self.backend.reserve(self.grant,1)

    def test_foreign_owner_or_scope_cannot_reserve_or_settle(self):
        self.backend.reserve(self.grant,40,request_id='request')
        for grant in (replace(self.grant,owner='foreign'),replace(self.grant,scope='foreign')):
            with self.subTest(grant=grant):
                with self.assertRaises(PolicyDenied):self.backend.reserve(grant,1)
                with self.assertRaises(PolicyDenied):self.backend.settle(grant,'request',0)
        self.assertEqual(self.session.report()['reserved_or_unknown_tokens'],40)

    def test_audit_failure_rolls_back_reservation_and_request(self):
        with patch.object(self.store,'_event',side_effect=GovernanceUnavailable('fixture audit unavailable')):
            with self.assertRaises(GovernanceUnavailable):self.backend.reserve(self.grant,40,request_id='request')
        self.assertEqual(self.session.report()['model_calls'],0)
        self.assertEqual(self.session.report()['reserved_or_unknown_tokens'],0)
        with self.store.transaction() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM governance_requests').fetchone()[0],0)

    def test_audit_failure_rolls_back_settlement(self):
        self.backend.reserve(self.grant,40,request_id='request')
        with patch.object(self.store,'_event',side_effect=GovernanceUnavailable('fixture audit unavailable')):
            with self.assertRaises(GovernanceUnavailable):self.backend.settle(self.grant,'request',7)
        report=self.session.report()
        self.assertEqual((report['spent_tokens'],report['reserved_or_unknown_tokens']),(0,40))

    def test_session_delegates_business_operations_without_sql_callbacks(self):
        backend=Mock();backend.reserve.return_value='receipt'
        backend.transaction_domain=self.store.transaction_domain
        self.store.budgets=backend
        self.assertEqual(self.session.reserve(5,request_id='supplied'),'receipt')
        self.session.settle('receipt',3,outcome='known')
        backend.reserve.assert_called_once_with(self.grant,5,request_id='supplied')
        backend.settle.assert_called_once_with(self.grant,'receipt',3,outcome='known')
