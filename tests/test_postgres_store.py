"""Driver-contract fixtures only: these tests do not validate PostgreSQL SQL."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from examples.check_postgres_connection import execute as check_connection
from keel.core import PolicyDenied
from keel.governance import ControlStore, GovernanceUnavailable
from keel.postgres_store import PostgresOperationStore, PostgresUnitOfWork
from keel.transaction_domain import require_shared_domain


class DriverError(Exception):
    sqlstate='08006'


class ConnectionFixture:
    def __init__(self):
        self.sql=[];self.closed=False;self.commits=0;self.rollbacks=0
        self.inserted=True;self.prior={'request_hash':'a'*64,'status':'pending','response':None}
        self.publish_count=1

    @contextmanager
    def transaction(self):
        try:yield self
        except BaseException:self.rollbacks+=1;raise
        else:self.commits+=1

    def execute(self,sql,parameters=None):
        self.sql.append((sql,parameters))
        if 'RETURNING operation_id' in sql:row={'operation_id':'operation'} if self.inserted else None
        elif 'FOR UPDATE' in sql:row=self.prior
        else:row=None
        return SimpleNamespace(fetchone=lambda:row,rowcount=self.publish_count)

    def close(self):self.closed=True


class PostgresStoreUnitTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{'KEEL_PG_UNIT_DSN':'secret-dsn-not-logged'})
        env.start();self.addCleanup(env.stop)
        self.connection=ConnectionFixture()
        self.driver=SimpleNamespace(Error=DriverError,connect=Mock(return_value=self.connection))
        self.store=PostgresUnitOfWork(dsn_env='KEEL_PG_UNIT_DSN')
        driver=patch.object(self.store,'_driver',return_value=(self.driver,None))
        driver.start();self.addCleanup(driver.stop)
        self.operations=PostgresOperationStore(self.store)

    def request(self,**changes):
        request={'principal':'worker','operation_id':'operation','request_hash':'a'*64,
            'prepare':lambda db:None,'apply':lambda db,context:{'ok':True},
            'replay':lambda db,context,value:value}
        return {**request,**changes}

    def test_nested_calls_share_connection_and_one_commit(self):
        with self.store.transaction() as outer:
            with self.store.transaction() as inner:self.assertIs(outer,inner)
        self.driver.connect.assert_called_once();self.assertEqual(self.connection.commits,1)
        self.assertTrue(self.connection.closed)

    def test_callback_error_rolls_back_without_retry(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction():raise RuntimeError('fixture')
        self.assertEqual(self.connection.rollbacks,1);self.driver.connect.assert_called_once()

    def test_driver_error_is_sanitized_and_not_retried(self):
        self.driver.connect.side_effect=DriverError('secret-dsn-not-logged')
        with self.assertRaises(GovernanceUnavailable) as caught:
            with self.store.transaction():pass
        self.assertNotIn('secret',str(caught.exception)+json.dumps(caught.exception.failure))
        self.assertEqual(caught.exception.failure['sqlstate'],'08006')
        self.driver.connect.assert_called_once()

    def test_close_error_does_not_leak_driver_message(self):
        with patch.object(self.connection,'close',side_effect=DriverError('secret')):
            with self.assertRaises(GovernanceUnavailable) as caught:
                with self.store.transaction():pass
        self.assertNotIn('secret',str(caught.exception))

    def test_schema_creation_requires_explicit_call(self):
        self.driver.connect.assert_not_called()
        self.operations.initialize_schema()
        self.assertTrue(any('CREATE TABLE' in sql for sql,_ in self.connection.sql))

    def test_new_receipt_uses_native_placeholders_and_transaction(self):
        result=self.operations.execute(**self.request())
        self.assertTrue(result['ok']);self.assertEqual(self.connection.commits,1)
        self.assertTrue(any('%s' in sql and 'ON CONFLICT' in sql for sql,_ in self.connection.sql))

    def test_completed_duplicate_does_not_call_apply(self):
        self.connection.inserted=False;self.connection.prior.update(status='complete',response='{"ok":true}')
        apply=Mock()
        self.assertTrue(self.operations.execute(**self.request(apply=apply))['ok'])
        apply.assert_not_called()

    def test_changed_input_is_denied_before_business_callback(self):
        self.connection.inserted=False
        apply=Mock()
        with self.assertRaises(PolicyDenied):self.operations.execute(**self.request(request_hash='b'*64,apply=apply))
        apply.assert_not_called();self.assertEqual(self.connection.rollbacks,1)

    def test_committed_pending_receipt_never_authorizes_replay(self):
        self.connection.inserted=False;apply=Mock()
        with self.assertRaises(GovernanceUnavailable):self.operations.execute(**self.request(apply=apply))
        apply.assert_not_called()

    def test_receipt_publication_failure_rolls_back(self):
        self.connection.publish_count=0
        with self.assertRaises(GovernanceUnavailable):self.operations.execute(**self.request())
        self.assertEqual(self.connection.rollbacks,1)

    def test_prepare_runs_before_cached_receipt(self):
        def denied(db):raise PolicyDenied('revoked')
        with self.assertRaises(PolicyDenied):self.operations.execute(**self.request(prepare=denied))
        self.assertFalse(any('INSERT INTO' in sql for sql,_ in self.connection.sql))

    def test_preflight_reports_unavailable_and_creates_sink_without_connect(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'missing'/'result'
            with patch('examples.check_postgres_connection.importlib.util.find_spec',return_value=None):
                result=check_connection(output,dsn_env='KEEL_PG_UNIT_DSN')
            self.assertEqual(result['status'],'unavailable')
            self.assertEqual(json.loads((output/'report.json').read_text())['migrations'],0)
        self.driver.connect.assert_not_called()

    def test_native_backend_cannot_be_mixed_with_sqlite_controller_domain(self):
        with tempfile.TemporaryDirectory() as temp:
            sqlite=ControlStore(Path(temp)/'control.sqlite')
            with self.assertRaises(GovernanceUnavailable):require_shared_domain(sqlite,operations=self.operations)
        self.driver.connect.assert_not_called()
