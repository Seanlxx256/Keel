"""Opt-in real PostgreSQL contracts; dedicated test DB only, fixture rows retained."""
import concurrent.futures
import os
import unittest
from unittest.mock import Mock
import uuid

from keel.core import PolicyDenied
from keel.postgres_store import PostgresOperationStore, PostgresUnitOfWork


ENABLED=bool(os.environ.get('KEEL_TEST_POSTGRES_DSN')) and os.environ.get('KEEL_TEST_POSTGRES_ALLOW_SCHEMA')=='yes'


@unittest.skipUnless(ENABLED,'Real PostgreSQL test DB and explicit schema-write opt-in not configured')
class PostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store=PostgresUnitOfWork(dsn_env='KEEL_TEST_POSTGRES_DSN')
        self.operations=PostgresOperationStore(self.store);self.operations.initialize_schema()
        with self.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS public.keel_operation_test_effects_v1 (
                principal TEXT NOT NULL, operation_id TEXT NOT NULL,
                PRIMARY KEY(principal,operation_id))''')
        self.principal='fixture-'+uuid.uuid4().hex;self.operation=uuid.uuid4().hex

    def request(self,principal=None,**changes):
        principal=principal or self.principal
        def apply(db,context):
            db.execute('INSERT INTO public.keel_operation_test_effects_v1 VALUES(%s,%s)',(principal,self.operation))
            return {'ok':True,'result':{'principal':principal}}
        result={'principal':principal,'operation_id':self.operation,'request_hash':'a'*64,
                'prepare':lambda db:None,'apply':apply,'replay':lambda db,context,value:value}
        return {**result,**changes}

    def count_effects(self):
        with self.store.transaction() as db:
            return db.execute('SELECT COUNT(*) AS count FROM public.keel_operation_test_effects_v1 WHERE operation_id=%s',
                              (self.operation,)).fetchone()['count']

    def test_concurrent_duplicates_commit_one_business_effect(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.operations.execute(**self.request()),range(8)))
        self.assertTrue(all(result==results[0] for result in results));self.assertEqual(self.count_effects(),1)

    def test_reopen_uses_receipt_without_business_callback(self):
        expected=self.operations.execute(**self.request())
        reopened=PostgresOperationStore(PostgresUnitOfWork(dsn_env='KEEL_TEST_POSTGRES_DSN'))
        apply=Mock()
        self.assertEqual(reopened.execute(**self.request(apply=apply)),expected)
        apply.assert_not_called();self.assertEqual(self.count_effects(),1)

    def test_callback_failure_rolls_back_effect_and_intent(self):
        apply=self.request()['apply']
        def fail(db,context):apply(db,context);raise RuntimeError('fixture rollback')
        with self.assertRaises(RuntimeError):self.operations.execute(**self.request(apply=fail))
        self.assertEqual(self.count_effects(),0)
        with self.store.transaction() as db:
            count=db.execute('SELECT COUNT(*) AS count FROM public.keel_operation_receipts_v1 WHERE principal=%s AND operation_id=%s',
                             (self.principal,self.operation)).fetchone()['count']
        self.assertEqual(count,0)

    def test_principal_namespaces_are_separate(self):
        self.operations.execute(**self.request())
        self.operations.execute(**self.request(principal=self.principal+'-other'))
        self.assertEqual(self.count_effects(),2)

    def test_changed_input_cannot_reapply(self):
        self.operations.execute(**self.request())
        with self.assertRaises(PolicyDenied):self.operations.execute(**self.request(request_hash='b'*64))
        self.assertEqual(self.count_effects(),1)
