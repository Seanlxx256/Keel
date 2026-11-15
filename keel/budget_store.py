"""Business-level budget transactions; SQLite is the only implemented backend."""
from dataclasses import dataclass
from typing import Protocol
import uuid

from .core import BudgetExceeded, PolicyDenied
from .run_store import RunGrant
from .tenant_quotas import check_reservation


@dataclass(frozen=True)
class BudgetGrant(RunGrant):
    """Trusted host run binding, not a worker-supplied authorization token."""


class BudgetStore(Protocol):
    @property
    def transaction_domain(self) -> object: ...
    def reserve(self, grant: BudgetGrant, tokens: int, *, request_id: str | None = None) -> str:
        """Atomically authorize, reserve scope/tenant quota, record intent.

        Duplicate request IDs are denied, never implicit replay permission.
        """
        ...

    def settle(self, grant: BudgetGrant, request_id: str, actual: int | None,
               *, outcome: str = 'completed') -> None:
        """Persist known or unknown usage, atomically with the audit outcome.

        Known repeated settlement is idempotent; conflicting usage is denied.
        Late settlement must not renew or reactivate an expired/finished run.
        """
        ...


class SqliteBudgetStore:
    def __init__(self, store):
        self.store=store

    @property
    def transaction_domain(self):return self.store.transaction_domain

    def reserve(self,grant,tokens,*,request_id=None):
        if type(tokens) is not int or tokens<=0:raise ValueError('Reservation must be positive integer tokens')
        request_id=request_id or uuid.uuid4().hex
        with self.store.transaction() as db:
            self.store.runs.require_active(grant)
            if db.execute('SELECT 1 FROM governance_requests WHERE id=?',(request_id,)).fetchone():
                raise PolicyDenied('Request ID already exists; never redispatch an uncertain call')
            check_reservation(db,grant.scope,tokens)
            changed=db.execute('''UPDATE governance_scopes SET held=held+?,calls=calls+1
                WHERE scope=? AND spent+held+?<=max_tokens AND calls<max_calls''',
                (tokens,grant.scope,tokens)).rowcount
            if not changed:raise BudgetExceeded('Shared governance token or model-call budget exhausted')
            db.execute('INSERT INTO governance_requests VALUES(?,?,?,NULL,?)',(request_id,grant.run_id,tokens,'dispatched'))
            self.store._event(db,grant.run_id,request_id,'model_intent',{'reserved_tokens':tokens})
        return request_id

    def settle(self,grant,request_id,actual,*,outcome='completed'):
        if actual is not None and (type(actual) is not int or actual<0):
            raise ValueError('Actual tokens must be a nonnegative integer or unknown')
        with self.store.transaction() as db:
            self.store.runs.get_bound(grant)
            row=db.execute('SELECT * FROM governance_requests WHERE id=? AND run_id=?',(request_id,grant.run_id)).fetchone()
            if not row:raise PolicyDenied('Unknown or foreign request')
            if row['status']=='settled':
                if row['actual']!=actual:raise PolicyDenied('Conflicting usage settlement')
                return
            if actual is None:
                db.execute("UPDATE governance_requests SET status='unknown' WHERE id=?",(request_id,))
            else:
                db.execute('UPDATE governance_scopes SET held=held-?,spent=spent+? WHERE scope=?',
                           (row['reserved'],actual,grant.scope))
                db.execute("UPDATE governance_requests SET actual=?,status='settled' WHERE id=?",(actual,request_id))
            self.store._event(db,grant.run_id,request_id,'model_outcome',{'actual_tokens':actual,'outcome':outcome,
                'reservation_exceeded':actual is not None and actual>row['reserved']})
