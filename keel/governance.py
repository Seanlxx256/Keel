"""Opt-in, same-host durable governance. SQLite is not a distributed database.

All records are written by the trusted host, not accepted from an agent/sidecar.
Unknown model usage keeps its reservation until an operator reconciles it.
Leases detect loss of contact; they never authorize replay of side effects.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import math
import sqlite3
import time
import uuid

from .core import BudgetExceeded, ModelError, PolicyDenied


class GovernanceUnavailable(PolicyDenied):
    """Required durable control/audit failed; no permission to dispatch work."""


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def reject_nonfinite(value):
    raise ValueError('Non-finite JSON number: '+value)


def validate_config(config):
    if config is None:
        return
    required = {'path', 'scope', 'max_tokens', 'max_model_calls'}
    if not isinstance(config, dict) or not required <= config.keys() or set(config) - required - {'lease_seconds', 'denied_tools'}:
        raise ValueError('governance requires path, scope, max_tokens and max_model_calls')
    for key in ('path', 'scope'):
        if not isinstance(config[key], str) or not config[key].strip():
            raise ValueError(f'governance.{key} must be nonempty text')
    for key in ('max_tokens', 'max_model_calls'):
        if type(config[key]) is not int or config[key] <= 0:
            raise ValueError(f'governance.{key} must be a positive integer')
    lease = config.get('lease_seconds', 3600)
    if type(lease) not in (int, float) or not math.isfinite(lease) or lease <= 0:
        raise ValueError('governance.lease_seconds must be finite and positive')
    denied = config.get('denied_tools', [])
    if not isinstance(denied, list) or any(not isinstance(t, str) or not t for t in denied) or len(set(denied)) != len(denied):
        raise ValueError('governance.denied_tools must be unique tool names')


class ControlStore:
    def __init__(self, path, *, clock=time.time, initialize=True):
        self.path = Path(path).resolve()
        self.clock = clock
        if not initialize:
            if not self.path.is_file():raise FileNotFoundError(self.path)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            schema='''
                CREATE TABLE IF NOT EXISTS governance_scopes (
                    scope TEXT PRIMARY KEY, policy TEXT NOT NULL,
                    max_tokens INTEGER NOT NULL, max_calls INTEGER NOT NULL,
                    spent INTEGER NOT NULL DEFAULT 0, held INTEGER NOT NULL DEFAULT 0,
                    calls INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS governance_runs (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, owner TEXT NOT NULL,
                    status TEXT NOT NULL, deadline REAL NOT NULL, identity TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS governance_requests (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, reserved INTEGER NOT NULL,
                    actual INTEGER, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS governance_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    action_id TEXT NOT NULL, kind TEXT NOT NULL, at REAL NOT NULL,
                    payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS governance_events_run ON governance_events(run_id,seq);
            '''
            # executescript implicitly commits an existing transaction.
            for statement in schema.split(';'):
                if statement.strip():db.execute(statement)

    @contextmanager
    def transaction(self):
        try:
            db = sqlite3.connect(self.path, timeout=2, isolation_level=None)
        except sqlite3.Error as error:
            raise GovernanceUnavailable('Required governance database unavailable: '+type(error).__name__) from error
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except sqlite3.Error as error:
            db.rollback()
            raise GovernanceUnavailable('Required governance transaction failed: '+type(error).__name__) from error
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def inspect(self, *, scope, run_id=None, after=0, limit=100):
        """Bounded host/operator view; not a remotely authenticated API."""
        if type(after) is not int or after < 0 or type(limit) is not int or not 1<=limit<=1000:
            raise ValueError('Expected bounded inspection pagination')
        db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=2)
        db.row_factory=sqlite3.Row
        try:
            quota=db.execute('SELECT scope,max_tokens,max_calls,spent,held,calls FROM governance_scopes WHERE scope=?',(scope,)).fetchone()
            if quota is None:
                raise KeyError('Unknown governance scope')
            if run_id is not None:
                run=db.execute('SELECT id,scope,status,deadline,identity FROM governance_runs WHERE id=? AND scope=?',(run_id,scope)).fetchone()
                if run is None:raise PolicyDenied('Run does not belong to requested scope')
                events=[dict(row) for row in db.execute('SELECT * FROM governance_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?',
                    (run_id,after,limit))]
                for row in events:row['payload']=json.loads(row['payload'])
                return {'scope':dict(quota),'run':dict(run),'events':events,
                        'next_after':events[-1]['seq'] if events else after}
            return {'scope':dict(quota),'runs':[dict(row) for row in db.execute(
                'SELECT id,status,deadline,identity FROM governance_runs WHERE scope=? ORDER BY id LIMIT ?', (scope,limit))]}
        finally:db.close()

    def _event(self, db, run_id, action_id, kind, payload):
        raw = encoded(payload)
        if len(raw.encode('utf-8')) > 65536:
            raise ValueError('Governance event payload exceeds 64 KiB; store an artifact reference')
        db.execute('INSERT INTO governance_events(run_id,action_id,kind,at,payload) VALUES(?,?,?,?,?)',
                   (run_id, action_id, kind, self.clock(), raw))

    def begin(self, config, run_id, identity):
        validate_config(config)
        policy = encoded(sorted(config.get('denied_tools', [])))
        owner = uuid.uuid4().hex
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO governance_scopes(scope,policy,max_tokens,max_calls) VALUES(?,?,?,?)',
                       (config['scope'], policy, config['max_tokens'], config['max_model_calls']))
            row = db.execute('SELECT * FROM governance_scopes WHERE scope=?', (config['scope'],)).fetchone()
            if (row['policy'], row['max_tokens'], row['max_calls']) != (policy, config['max_tokens'], config['max_model_calls']):
                raise PolicyDenied('Governance scope configuration changed; use a new explicit scope')
            db.execute('INSERT INTO governance_runs VALUES(?,?,?,?,?,?)',
                       (run_id, config['scope'], owner, 'running', self.clock()+config.get('lease_seconds',3600), identity))
            self._event(db, run_id, owner, 'run_started', {'scope': config['scope'], 'identity': identity})
        return Session(self, config, run_id, owner)

    def reconcile_expired(self, *, scope=None):
        """Detect expired runs, preserve reservations and never replay work."""
        with self.transaction() as db:
            rows = db.execute("SELECT id FROM governance_runs WHERE status='running' AND deadline<=?"+
                (' AND scope=?' if scope is not None else ''),
                (self.clock(),scope) if scope is not None else (self.clock(),)).fetchall()
            for row in rows:
                db.execute("UPDATE governance_runs SET status='unreachable' WHERE id=?", (row['id'],))
                db.execute("UPDATE governance_requests SET status='unknown' WHERE run_id=? AND status='dispatched'", (row['id'],))
                self._event(db,row['id'],uuid.uuid4().hex,'lease_expired',{'replay_authorized':False})
        return [row['id'] for row in rows]

    def events(self, run_id, *, after=0, limit=100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Expected bounded event pagination')
        with self.transaction() as db:
            return [dict(row) for row in db.execute('SELECT * FROM governance_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?', (run_id,after,limit))]


class Session:
    def __init__(self, store, config, run_id, owner):
        self.store, self.config, self.run_id, self.owner = store, dict(config), run_id, owner

    def _active(self, db):
        row = db.execute('SELECT * FROM governance_runs WHERE id=?', (self.run_id,)).fetchone()
        if not row or row['owner'] != self.owner or row['status'] != 'running' or row['deadline'] <= self.store.clock():
            raise PolicyDenied('Governance run inactive or lease expired; reconcile before further work')
        db.execute('UPDATE governance_runs SET deadline=? WHERE id=?',
                   (self.store.clock()+self.config.get('lease_seconds',3600), self.run_id))

    def event(self, kind, payload, *, action_id=None):
        with self.store.transaction() as db:
            self._active(db)
            self.store._event(db,self.run_id,action_id or uuid.uuid4().hex,kind,payload)

    def tool_started(self, role, tool, action_id):
        denied = tool in self.config.get('denied_tools', [])
        self.event('tool_denied' if denied else 'tool_intent', {'role':role,'tool':tool}, action_id=action_id)
        if denied:
            raise PolicyDenied('Tool denied by durable governance policy: '+tool)

    def reserve(self, tokens, *, request_id=None):
        if type(tokens) is not int or tokens <= 0:
            raise ValueError('Reservation must be positive integer tokens')
        request_id = request_id or uuid.uuid4().hex
        with self.store.transaction() as db:
            self._active(db)
            if db.execute('SELECT 1 FROM governance_requests WHERE id=?', (request_id,)).fetchone():
                raise PolicyDenied('Request ID already exists; never redispatch an uncertain call')
            changed = db.execute('UPDATE governance_scopes SET held=held+?,calls=calls+1 WHERE scope=? AND spent+held+?<=max_tokens AND calls<max_calls',
                                 (tokens,self.config['scope'],tokens)).rowcount
            if not changed:
                raise BudgetExceeded('Shared governance token or model-call budget exhausted')
            db.execute('INSERT INTO governance_requests VALUES(?,?,?,NULL,?)', (request_id,self.run_id,tokens,'dispatched'))
            self.store._event(db,self.run_id,request_id,'model_intent',{'reserved_tokens':tokens})
        return request_id

    def settle(self, request_id, actual, *, outcome='completed'):
        """Late usage may settle an unreachable run; it does not reactivate it."""
        if actual is not None and (type(actual) is not int or actual < 0):
            raise ValueError('Actual tokens must be a nonnegative integer or unknown')
        with self.store.transaction() as db:
            run = db.execute('SELECT owner FROM governance_runs WHERE id=?',(self.run_id,)).fetchone()
            row = db.execute('SELECT * FROM governance_requests WHERE id=? AND run_id=?',(request_id,self.run_id)).fetchone()
            if not run or run['owner'] != self.owner or not row:
                raise PolicyDenied('Unknown or foreign request')
            if row['status'] == 'settled':
                if row['actual'] != actual:
                    raise PolicyDenied('Conflicting usage settlement')
                return
            if actual is None:
                db.execute("UPDATE governance_requests SET status='unknown' WHERE id=?",(request_id,))
            else:
                db.execute('UPDATE governance_scopes SET held=held-?,spent=spent+? WHERE scope=?',
                           (row['reserved'],actual,self.config['scope']))
                db.execute("UPDATE governance_requests SET actual=?,status='settled' WHERE id=?",(actual,request_id))
            self.store._event(db,self.run_id,request_id,'model_outcome',{'actual_tokens':actual,'outcome':outcome,
                'reservation_exceeded':actual is not None and actual>row['reserved']})

    def finish(self, status):
        if status not in {'passed','failed'}:
            raise ValueError('Expected final runtime status')
        with self.store.transaction() as db:
            self._active(db)
            db.execute("UPDATE governance_requests SET status='unknown' WHERE run_id=? AND status='dispatched'", (self.run_id,))
            db.execute('UPDATE governance_runs SET status=? WHERE id=?',(status,self.run_id))
            self.store._event(db,self.run_id,self.owner,'run_finished',{'status':status})
        return self.report()

    def report(self):
        with self.store.transaction() as db:
            row = dict(db.execute('SELECT * FROM governance_scopes WHERE scope=?',(self.config['scope'],)).fetchone())
            run = db.execute('SELECT status FROM governance_runs WHERE id=?',(self.run_id,)).fetchone()
        return {'path':str(self.store.path),'scope':self.config['scope'],'run_id':self.run_id,
                'status':run['status'],'spent_tokens':row['spent'],'reserved_or_unknown_tokens':row['held'],
                'model_calls':row['calls'],'max_tokens':row['max_tokens'],'max_model_calls':row['max_calls'],
                'scope_note':'Same-host SQLite coordination; reservations are estimates, not provider billing guarantees.'}


class GovernedModel:
    """Govern existing model calls; never retry a paid call in this wrapper."""
    def __init__(self, model, session):
        self.model, self.session = model, session

    def __getattr__(self, name):
        return getattr(self.model,name)

    def complete(self, messages, *, timeout, max_output):
        return self._call(messages,timeout,max_output,None)

    def complete_json(self, messages, *, schema, timeout, max_output):
        return self._call(messages,timeout,max_output,schema)

    def _call(self,messages,timeout,max_output,schema):
        if type(max_output) is not int or max_output <= 0:
            raise ValueError('max_output must be a positive integer')
        # Account for serialized schema as well as messages. This byte-based
        # estimate is not a claim of exact provider tokenization.
        estimate=len(encoded({'messages':messages,'schema':schema}).encode('utf-8'))+max_output
        request=self.session.reserve(estimate)
        try:
            method=getattr(self.model,'complete_json',None)
            reply=(method(messages,schema=schema,timeout=timeout,max_output=max_output)
                   if schema is not None and callable(method) else
                   self.model.complete(messages,timeout=timeout,max_output=max_output))
        except BaseException as error:
            count=getattr(error,'tokens',None)
            self.session.settle(request,count if type(count) is int and count>=0 else None,outcome=type(error).__name__)
            raise
        count=getattr(reply,'tokens',None)
        self.session.settle(request,count if type(count) is int and count>=0 else None)
        if type(count) is int and count > estimate:
            raise ModelError('Provider usage exceeded governance reservation; usage recorded, inspect counting policy',tokens=count)
        if schema is not None:
            try:
                json.loads(reply.content,parse_constant=reject_nonfinite)
            except (ValueError,TypeError):
                self.session.event('model_format_rejected',{'request_id':request,'reason':'invalid_json'})
                raise ModelError('Governed structured completion is not valid JSON',tokens=count) from None
        return reply


def attach(config, workspace, output, identity):
    if config is None:
        return None
    path=Path(config['path']).resolve()
    if path.is_relative_to(workspace.root):
        raise ValueError('Governance database must be outside the untrusted repository')
    session=ControlStore(path).begin(config,uuid.uuid4().hex,identity)
    workspace.governance=session
    return session


def govern_model(model, session):
    """Retry-owning wrappers must attach governance inside their retry loop."""
    if isinstance(model, GovernedModel):
        if model.session is not session:raise PolicyDenied('Model belongs to another governance session')
        return model
    binder=getattr(type(model),'bind_governance',None)
    if callable(binder):
        model.bind_governance(session)
        return model
    if getattr(model,'transport_retries',0):
        raise ValueError('Retry-owning model requires bind_governance before enabling shared governance')
    return GovernedModel(model,session)
