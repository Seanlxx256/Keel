"""Run authorization/lifecycle business contract and SQLite implementation."""
from dataclasses import dataclass, replace
from typing import Protocol
import uuid

from .core import PolicyDenied


@dataclass(frozen=True)
class RunGrant:
    """Trusted host binding, never a bearer credential for an untrusted worker."""
    run_id: str
    owner: str
    scope: str
    lease_seconds: float


@dataclass(frozen=True)
class RunState:
    run_id: str
    scope: str
    owner: str
    status: str
    deadline: float
    identity: str


class RunStore(Protocol):
    @property
    def transaction_domain(self) -> object: ...
    def create(self,config: dict,run_id: str,identity: str) -> RunGrant: ...
    def get_bound(self,grant: RunGrant) -> RunState: ...
    def require_active(self,grant: RunGrant) -> RunState: ...
    def finish(self,grant: RunGrant,status: str) -> None: ...
    def reconcile_expired(self,*,scope: str | None = None) -> list[str]: ...
    def bind_remote(self,grant: RunGrant,principal: str,task_id: str,grant_hash: str) -> None: ...
    def authorize_remote(self,*,run_id: str,principal: str,task_id: str,scope: str,
                         grant_hash: str,lease_seconds: float) -> RunGrant: ...
    def remote_task(self,grant: RunGrant) -> str: ...


class SqliteRunStore:
    def __init__(self,store):self.store=store

    @property
    def transaction_domain(self):return self.store.transaction_domain

    def create(self,config,run_id,identity):
        from .governance import encoded, validate_config
        validate_config(config)
        policy=encoded(sorted(config.get('denied_tools',[])));owner=uuid.uuid4().hex
        lease=config.get('lease_seconds',3600)
        with self.store.transaction() as db:
            db.execute('INSERT OR IGNORE INTO governance_scopes(scope,policy,max_tokens,max_calls) VALUES(?,?,?,?)',
                       (config['scope'],policy,config['max_tokens'],config['max_model_calls']))
            row=db.execute('SELECT policy,max_tokens,max_calls FROM governance_scopes WHERE scope=?',(config['scope'],)).fetchone()
            if tuple(row)!=(policy,config['max_tokens'],config['max_model_calls']):
                raise PolicyDenied('Governance scope configuration changed; use a new explicit scope')
            db.execute('INSERT INTO governance_runs VALUES(?,?,?,?,?,?)',
                       (run_id,config['scope'],owner,'running',self.store.clock()+lease,identity))
            self.store._event(db,run_id,owner,'run_started',{'scope':config['scope'],'identity':identity})
        return RunGrant(run_id,owner,config['scope'],lease)

    def _bound(self,db,grant):
        row=db.execute('SELECT * FROM governance_runs WHERE id=?',(grant.run_id,)).fetchone()
        if not row or row['owner']!=grant.owner or row['scope']!=grant.scope:
            raise PolicyDenied('Unknown or foreign run binding')
        return RunState(row['id'],row['scope'],row['owner'],row['status'],row['deadline'],row['identity'])

    def get_bound(self,grant):
        with self.store.transaction() as db:return self._bound(db,grant)

    def _active(self,db,grant):
        state=self._bound(db,grant)
        if state.status!='running' or state.deadline<=self.store.clock():
            raise PolicyDenied('Governance run inactive or lease expired; reconcile before further work')
        deadline=self.store.clock()+grant.lease_seconds
        db.execute('UPDATE governance_runs SET deadline=? WHERE id=?',(deadline,grant.run_id))
        return replace(state,deadline=deadline)

    def require_active(self,grant):
        with self.store.transaction() as db:return self._active(db,grant)

    def finish(self,grant,status):
        if status not in {'passed','failed'}:raise ValueError('Expected final runtime status')
        with self.store.transaction() as db:
            self._active(db,grant)
            db.execute("UPDATE governance_requests SET status='unknown' WHERE run_id=? AND status='dispatched'",(grant.run_id,))
            db.execute('UPDATE governance_runs SET status=? WHERE id=?',(status,grant.run_id))
            self.store._event(db,grant.run_id,grant.owner,'run_finished',{'status':status})

    def reconcile_expired(self,*,scope=None):
        with self.store.transaction() as db:
            rows=db.execute("SELECT id FROM governance_runs WHERE status='running' AND deadline<=?"+
                (' AND scope=?' if scope is not None else ''),
                (self.store.clock(),scope) if scope is not None else (self.store.clock(),)).fetchall()
            for row in rows:
                db.execute("UPDATE governance_runs SET status='unreachable' WHERE id=?",(row['id'],))
                db.execute("UPDATE governance_requests SET status='unknown' WHERE run_id=? AND status='dispatched'",(row['id'],))
                self.store._event(db,row['id'],uuid.uuid4().hex,'lease_expired',{'replay_authorized':False})
        return [row['id'] for row in rows]

    def bind_remote(self,grant,principal,task_id,grant_hash):
        with self.store.transaction() as db:
            self._bound(db,grant)
            db.execute('INSERT INTO remote_run_bindings VALUES(?,?,?,?)',(grant.run_id,principal,task_id,grant_hash))

    def authorize_remote(self,*,run_id,principal,task_id,scope,grant_hash,lease_seconds):
        with self.store.transaction() as db:
            row=db.execute('''SELECT r.owner,r.scope,b.principal,b.task_id,b.grant_hash
                FROM governance_runs r JOIN remote_run_bindings b ON r.id=b.run_id WHERE r.id=?''',(run_id,)).fetchone()
            if not row or (row['principal'],row['task_id'],row['scope'],row['grant_hash'])!=(principal,task_id,scope,grant_hash):
                raise PolicyDenied('Run unavailable to this principal or grant changed')
        # Ownership only: inspection/late accounting must not renew execution.
        return RunGrant(run_id,row['owner'],scope,lease_seconds)

    def remote_task(self,grant):
        with self.store.transaction() as db:
            self._bound(db,grant)
            row=db.execute('SELECT task_id FROM remote_run_bindings WHERE run_id=?',(grant.run_id,)).fetchone()
            if not row:raise PolicyDenied('Run has no remote task binding')
            return row['task_id']
