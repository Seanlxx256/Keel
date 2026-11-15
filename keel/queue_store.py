"""Task queue storage contract and existing SQLite implementation."""
import hashlib
import json
import math
from typing import Any, Protocol

from .core import PolicyDenied
from .governance import encoded


def text(value):
    if not isinstance(value,str) or not value.strip() or len(value)>256:
        raise ValueError('Expected nonempty bounded identifier')
    return value


class QueueStore(Protocol):
    """Trusted controller queue transactions, not direct untrusted worker APIs.

    Implementations must join the controller receipt transaction. A lost lease
    means unknown effects, never automatic requeue or execution permission.
    Worker result reports are not independent acceptance evidence.
    """
    @property
    def transaction_domain(self) -> object: ...
    def enqueue(self,item_id: str,principal: str,task_id: str,payload: dict[str,Any]) -> dict: ...
    def claim(self,principal: str,task_id: str,run_id: str,run_deadline: float) -> dict: ...
    def transition(self,principal: str,task_id: str,run_id: str,item_id: str,
                   fence: int,action: str,report: dict | None = None) -> dict: ...
    def status(self,principal: str,task_id: str,item_id: str) -> dict: ...
    def renew(self,principal: str,task_id: str,run_id: str,item_id: str,
              fence: int,run_deadline: float) -> dict: ...
    def requeue(self,item_id: str,fence: int,reason: str) -> dict: ...


class SqliteQueueStore:
    @property
    def transaction_domain(self):return self.store.transaction_domain

    def __init__(self,store):
        self.store=store
        with store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS control_tasks (
                id TEXT PRIMARY KEY, principal TEXT NOT NULL, task_id TEXT NOT NULL,
                payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                status TEXT NOT NULL, fence INTEGER NOT NULL DEFAULT 0,
                run_id TEXT, deadline REAL, report TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS control_task_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL,
                fence INTEGER NOT NULL, at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS control_tasks_claim ON control_tasks(principal,task_id,status,id)')

    def _event(self,db,item,kind,payload):
        db.execute('INSERT INTO control_task_events(task,fence,at,kind,payload) VALUES(?,?,?,?,?)',
                   (item['id'],item['fence'],self.store.clock(),kind,encoded(payload)))

    def enqueue(self,item_id,principal,task_id,payload):
        """Trusted controller producer only; not exposed as a worker RPC."""
        for value in (item_id,principal,task_id):text(value)
        if not isinstance(payload,dict):raise ValueError('Task payload must be an object')
        raw=encoded(payload)
        if len(raw.encode())>32768:raise ValueError('Task payload too large; use artifact references')
        digest=hashlib.sha256(raw.encode()).hexdigest()
        with self.store.transaction() as db:
            old=db.execute('SELECT * FROM control_tasks WHERE id=?',(item_id,)).fetchone()
            if old:
                if (old['principal'],old['task_id'],old['payload_hash'])!=(principal,task_id,digest):
                    raise PolicyDenied('Task identity already exists with different input')
                return {'id':item_id,'status':old['status'],'reused':True}
            db.execute('INSERT INTO control_tasks(id,principal,task_id,payload,payload_hash,status) VALUES(?,?,?,?,?,?)',
                       (item_id,principal,task_id,raw,digest,'queued'))
            self._event(db,{'id':item_id,'fence':0},'enqueued',{'payload_hash':digest})
        return {'id':item_id,'status':'queued','reused':False}

    def _expire(self,db):
        rows=db.execute("SELECT * FROM control_tasks WHERE status IN ('claimed','running') AND deadline<=?",
                        (self.store.clock(),)).fetchall()
        for row in rows:
            db.execute("UPDATE control_tasks SET status='unknown' WHERE id=?",(row['id'],))
            self._event(db,row,'lease_expired',{'run_id':row['run_id'],'external_effect':'unknown'})

    def claim(self,principal,task_id,run_id,run_deadline):
        with self.store.transaction() as db:
            self._expire(db)
            deadline=min(run_deadline,self.store.clock()+300)
            if not math.isfinite(deadline) or deadline<=self.store.clock():raise PolicyDenied('Run lease expired')
            # A run must resolve its outstanding claim before taking another.
            old=db.execute("SELECT id FROM control_tasks WHERE run_id=? AND status IN ('claimed','running','unknown')",
                           (run_id,)).fetchone()
            if old:raise PolicyDenied('Run already has an outstanding or uncertain task')
            row=db.execute("SELECT * FROM control_tasks WHERE principal=? AND task_id=? AND status='queued' ORDER BY id LIMIT 1",
                           (principal,task_id)).fetchone()
            if row is None:return {'task':None}
            fence=row['fence']+1
            db.execute("UPDATE control_tasks SET status='claimed',fence=?,run_id=?,deadline=?,report=NULL WHERE id=?",
                       (fence,run_id,deadline,row['id']))
            self._event(db,{'id':row['id'],'fence':fence},'claimed',{'run_id':run_id,'deadline':deadline})
            return {'dispatch_allowed':True,'task':{'id':row['id'],'fence':fence,'deadline':deadline,
                            'payload':json.loads(row['payload']),'payload_sha256':row['payload_hash']}}

    def transition(self,principal,task_id,run_id,item_id,fence,action,report=None):
        text(item_id)
        if type(fence) is not int or fence<1:raise ValueError('Invalid fencing token')
        if action not in {'start','finish'}:raise ValueError('Invalid queue transition')
        if action=='finish':
            if not isinstance(report,dict) or set(report)!={'status','artifact_sha256'}:
                raise ValueError('Expected status and artifact_sha256')
            digest=report['artifact_sha256']
            if (not isinstance(report['status'],str) or report['status'] not in {'passed','failed'} or not isinstance(digest,str)
                    or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest)):
                raise ValueError('Invalid worker result reference')
        with self.store.transaction() as db:
            self._expire(db)
            row=db.execute('SELECT * FROM control_tasks WHERE id=?',(item_id,)).fetchone()
            if (not row or (row['principal'],row['task_id'],row['run_id'],row['fence'])
                    !=(principal,task_id,run_id,fence)):
                raise PolicyDenied('Task unavailable or stale fencing token')
            expected='claimed' if action=='start' else 'running'
            if row['status']!=expected:raise PolicyDenied('Task transition denied: '+row['status'])
            status='running' if action=='start' else 'reported_'+report['status']
            db.execute('UPDATE control_tasks SET status=?,report=? WHERE id=?',
                       (status,encoded(report) if report is not None else None,item_id))
            self._event(db,row,action,{'run_id':run_id,'status':status,
                                     'authority':'worker report, not independent acceptance'})
            return {'id':item_id,'fence':fence,'status':status,'dispatch_allowed':action=='start'}

    def status(self,principal,task_id,item_id):
        text(item_id)
        with self.store.transaction() as db:
            self._expire(db)
            row=db.execute('SELECT * FROM control_tasks WHERE id=?',(item_id,)).fetchone()
            if not row or (row['principal'],row['task_id'])!=(principal,task_id):
                raise PolicyDenied('Task unavailable')
            return {key:row[key] for key in ('id','status','fence','run_id','deadline','payload_hash','report')}

    def renew(self,principal,task_id,run_id,item_id,fence,run_deadline):
        text(item_id)
        if type(fence) is not int or fence<1:raise ValueError('Invalid fencing token')
        with self.store.transaction() as db:
            self._expire(db)
            row=db.execute('SELECT * FROM control_tasks WHERE id=?',(item_id,)).fetchone()
            if (not row or (row['principal'],row['task_id'],row['run_id'],row['fence'])
                    !=(principal,task_id,run_id,fence) or row['status'] not in {'claimed','running'}):
                raise PolicyDenied('Task lease cannot be renewed')
            deadline=min(run_deadline,self.store.clock()+300)
            if not math.isfinite(deadline) or deadline<=self.store.clock():raise PolicyDenied('Run lease expired')
            db.execute('UPDATE control_tasks SET deadline=? WHERE id=?',(deadline,item_id))
            self._event(db,row,'lease_renewed',{'deadline':deadline})
            return {'id':item_id,'fence':fence,'deadline':deadline}

    def requeue(self,item_id,fence,reason):
        """Trusted operator decision after external-effect inspection; never automatic."""
        text(item_id);text(reason)
        if type(fence) is not int:raise ValueError('Expected exact fencing token')
        with self.store.transaction() as db:
            self._expire(db)
            row=db.execute('SELECT * FROM control_tasks WHERE id=?',(item_id,)).fetchone()
            if not row or row['fence']!=fence or row['status'] not in {'unknown','reported_failed'}:
                raise PolicyDenied('Task is not eligible for explicit requeue')
            self._event(db,row,'operator_requeue',{'reason':reason,'previous_run_id':row['run_id']})
            db.execute("UPDATE control_tasks SET status='queued',run_id=NULL,deadline=NULL WHERE id=?",(item_id,))
            return {'id':item_id,'status':'queued','previous_fence':fence}
