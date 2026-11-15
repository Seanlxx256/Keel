import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest

from keel.core import PolicyDenied
from keel.governance import ControlStore, GovernanceUnavailable
from keel.operation_store import SqliteOperationStore


class OperationStoreContractTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'control.sqlite'
        self.store=ControlStore(self.path);self.operations=SqliteOperationStore(self.store)
        with self.store.transaction() as db:
            db.execute('CREATE TABLE effects (principal TEXT NOT NULL)')

    def request(self,principal='a',fingerprint='a'*64,prepare=None):
        def apply(db,context):
            db.execute('INSERT INTO effects VALUES(?)',(principal,))
            return {'ok':True,'result':{'principal':principal}}
        return dict(principal=principal,operation_id='same-id',request_hash=fingerprint,
                    prepare=prepare or (lambda db:None),apply=apply,
                    replay=lambda db,context,value:value)

    def effects(self):
        with self.store.transaction() as db:
            return [row['principal'] for row in db.execute('SELECT * FROM effects')]

    def test_reopen_reuses_committed_response_without_reapplying(self):
        expected=self.operations.execute(**self.request())
        reopened=SqliteOperationStore(ControlStore(self.path))
        self.assertEqual(reopened.execute(**self.request()),expected)
        self.assertEqual(self.effects(),['a'])

    def test_same_id_in_different_authenticated_principal_namespaces(self):
        first=self.operations.execute(**self.request('a'))
        second=self.operations.execute(**self.request('b'))
        self.assertNotEqual(first,second)
        self.assertEqual(self.effects(),['a','b'])

    def test_changed_input_is_denied_without_additional_effect(self):
        self.operations.execute(**self.request())
        with self.assertRaises(PolicyDenied):self.operations.execute(**self.request(fingerprint='b'*64))
        self.assertEqual(self.effects(),['a'])

    def test_authorization_is_checked_before_cached_receipt(self):
        self.operations.execute(**self.request())
        def denied(db):raise PolicyDenied('grant revoked')
        with self.assertRaises(PolicyDenied):self.operations.execute(**self.request(prepare=denied))
        self.assertEqual(self.effects(),['a'])

    def test_required_receipt_failure_rolls_back_business_mutation(self):
        with self.store.transaction() as db:
            db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON remote_operations BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(GovernanceUnavailable):self.operations.execute(**self.request())
        self.assertEqual(self.effects(),[])

    def test_existing_legacy_schema_receipt_is_preserved(self):
        expected={'ok':True,'result':{'legacy':True}}
        with self.store.transaction() as db:
            db.execute('INSERT INTO remote_operations VALUES(?,?,?,?)',('a','same-id','a'*64,json.dumps(expected)))
        self.assertEqual(SqliteOperationStore(self.store).execute(**self.request()),expected)
        self.assertEqual(self.effects(),[])

    def test_concurrent_duplicate_transactions_apply_once(self):
        def invoke(_):
            backend=SqliteOperationStore(ControlStore(self.path))
            return backend.execute(**self.request())
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            replies=list(pool.map(invoke,range(8)))
        self.assertTrue(all(reply==replies[0] for reply in replies))
        self.assertEqual(self.effects(),['a'])

    def test_nonrecorded_read_does_not_publish_receipt(self):
        request=self.request();request['apply']=lambda db,context:{'ok':True,'result':{}}
        self.operations.execute(**request,record=False)
        with self.store.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM remote_operations').fetchone()[0],0)
