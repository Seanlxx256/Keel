"""Atomic control-operation receipts: first storage extraction, SQLite backend.

Callbacks currently receive the existing controller SQL transaction. This is a
transitional boundary, not a drop-in PostgreSQL implementation. Callbacks must
only perform local transactional work, never dispatch a provider/tool/sandbox.
"""
from typing import Any, Callable, Protocol
import json

from .core import PolicyDenied
from .governance import encoded


def validate_operation_request(principal,operation_id,request_hash,record):
    for value in (principal,operation_id):
        if not isinstance(value,str) or not value or len(value)>256:
            raise ValueError('Invalid operation namespace or identifier')
    if (not isinstance(request_hash,str) or len(request_hash)!=64
            or any(char not in '0123456789abcdef' for char in request_hash)):
        raise ValueError('Invalid operation request fingerprint')
    if type(record) is not bool:raise ValueError('record must be boolean')


class OperationStore(Protocol):
    @property
    def transaction_domain(self) -> object: ...
    def execute(self, *, principal: str, operation_id: str, request_hash: str,
                prepare: Callable, apply: Callable, replay: Callable,
                record: bool = True) -> dict[str, Any]:
        """Authorize, apply and publish a receipt in one transaction.

        prepare also runs on cache hits; replay never re-applies the operation.
        Namespace is a server-authenticated principal, not caller-supplied tenant
        text. Backend failures must not return permission to dispatch work.
        """
        ...


class SqliteOperationStore:
    @property
    def transaction_domain(self):return self.store.transaction_domain

    def __init__(self, store):
        self.store=store
        with store.transaction() as db:
            # Same schema/name as the legacy controller: existing receipts remain.
            db.execute('''CREATE TABLE IF NOT EXISTS remote_operations (
                principal TEXT NOT NULL, operation_id TEXT NOT NULL,
                request_hash TEXT NOT NULL, response TEXT NOT NULL,
                PRIMARY KEY(principal,operation_id))''')

    def execute(self, *, principal, operation_id, request_hash, prepare, apply,
                replay, record=True):
        validate_operation_request(principal,operation_id,request_hash,record)
        with self.store.transaction() as db:
            context=prepare(db)
            prior=db.execute('SELECT request_hash,response FROM remote_operations WHERE principal=? AND operation_id=?',
                             (principal,operation_id)).fetchone()
            if prior:
                if prior['request_hash']!=request_hash:
                    raise PolicyDenied('Operation ID reused with different parameters')
                return replay(db,context,json.loads(prior['response']))
            response=apply(db,context)
            if record:
                db.execute('INSERT INTO remote_operations VALUES(?,?,?,?)',
                           (principal,operation_id,request_hash,encoded(response)))
            return response
