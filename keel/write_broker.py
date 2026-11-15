"""Explicit replacement effects, persisted before dispatch and never replayed."""
import hashlib
import json
import os
from contextlib import ExitStack

from .core import Budget, Ledger, Limits, PolicyDenied, Trace
from .governance import GovernanceUnavailable, encoded
from .tool_broker import ReadWorkspace
from .workspace import Workspace
from .file_lock import exclusive_file


class WriteWorkspace(ReadWorkspace):
    def __init__(self,*args,writable,**kwargs):
        self.writable=frozenset(writable);self.effect_attempted=False
        super().__init__(*args,**kwargs)

    def path(self,relative,write=False):
        path=super().path(relative,write=False)
        if write:
            if relative not in self.writable:raise PolicyDenied('File outside controller write catalog')
            Workspace.path(self,relative,write=True)  # Protected tests/metadata and hard-link checks.
        return path

    def _write_replacement(self,path,raw):
        self.effect_attempted=True
        super()._write_replacement(path,raw)


class WriteBroker:
    def __init__(self,service):
        self.service=service;self.read=service.read_broker
        with service.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS broker_write_requests (
                principal TEXT NOT NULL, operation_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                run_id TEXT NOT NULL, path_key TEXT NOT NULL, path TEXT NOT NULL,
                status TEXT NOT NULL, before_hash TEXT NOT NULL, after_hash TEXT NOT NULL,
                response TEXT, PRIMARY KEY(principal,operation_id))''')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS broker_pending_path ON broker_write_requests(path_key) WHERE status='inflight'")
            db.execute('''CREATE TABLE IF NOT EXISTS broker_write_resolutions (
                principal TEXT NOT NULL, operation_id TEXT NOT NULL, identity TEXT NOT NULL,
                response TEXT NOT NULL, PRIMARY KEY(principal,operation_id))''')

    def _path_lock(self,path):
        key=hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()
        folder=self.service.store.path.with_name(self.service.store.path.name+'.write-locks')
        return exclusive_file(folder/(key+'.lock'))

    def _approved_path(self,principal,row):
        spec=self.read.repositories[principal['task_id']]
        validator=object.__new__(WriteWorkspace)
        validator.root=spec['root'];validator.allowed=frozenset(spec['files'])
        validator.writable=frozenset(spec['writable_files'])
        path=validator.path(row['path'],write=True)
        if os.path.normcase(str(path))!=row['path_key']:raise PolicyDenied('Recorded write path changed identity')
        return path

    def capability(self,principal):
        spec=self.read.repositories.get(principal['task_id'])
        if spec and spec['writable_files'] and 'replace' in principal['tools'].get('implementer',[]):
            return {'replace':True,'files':sorted(spec['writable_files']),
                    'policy_sha256':self.read.policy_hashes[principal['task_id']]}
        return None

    def execute(self,principal_id,request):
        if (not isinstance(request,dict) or set(request)!={'operation_id','action','run_id','data'}
                or request['action']!='tool_replace' or not isinstance(request['operation_id'],str)
                or not 0<len(request['operation_id'])<=256):raise ValueError('Invalid replacement envelope')
        principal=self.service.principals[principal_id];data=request['data']
        if not self.capability(principal):raise PolicyDenied('Controller replacement not granted')
        if not isinstance(data,dict) or set(data)!={'path','old','new','before_sha256'}:
            raise ValueError('Replacement requires path, old, new and before_sha256')
        from .gateway import ToolGateway
        ToolGateway._validate('replace',{key:data[key] for key in ('path','old','new')})
        expected=data['before_sha256']
        if not isinstance(expected,str) or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):
            raise ValueError('Expected SHA256 of source bytes')
        if len(encoded(request).encode())>131072:raise ValueError('Replacement exceeds transport capacity')
        spec=self.read.repositories[principal['task_id']]
        fingerprint=hashlib.sha256(encoded(request).encode()+self.read.policy_hashes[principal['task_id']].encode()).hexdigest()
        if not self.read.slot.acquire(blocking=False):raise GovernanceUnavailable('Controller file broker busy')
        ledger=None;ws=None;locks=ExitStack()
        try:
            with self.service.store.transaction() as db:
                session=self.service._session(db,principal,request['run_id'])
                prior=db.execute('SELECT * FROM broker_write_requests WHERE principal=? AND operation_id=?',
                                 (principal_id,request['operation_id'])).fetchone()
                if prior:
                    if prior['request_hash']!=fingerprint:raise PolicyDenied('Replacement operation ID changed input')
                    if prior['status']=='inflight':raise GovernanceUnavailable('Replacement outcome unknown; inspect before any new write')
                    response=json.loads(prior['response'])
                    if response.get('ok'):response['result']['historical_response']=True
                    return response
                session._active(db)
            folder=self.read.evidence/session.run_id;folder.mkdir(parents=True,exist_ok=True)
            ledger=Ledger(folder/'writes.sqlite')
            ws=WriteWorkspace(spec['root'],Budget(Limits(max_wallclock=5,max_tool_calls=4)),ledger,
                              Trace(folder/'writes.jsonl'),allowed=spec['files'],writable=spec['writable_files'],memoization=False)
            path=ws.path(data['path'],write=True)
            locks.enter_context(self._path_lock(path))
            before=path.read_bytes()
            if hashlib.sha256(before).hexdigest()!=expected:raise PolicyDenied('Replacement source hash is stale')
            text=before.decode('utf-8')
            if not data['old'] or data['old']==data['new'] or text.count(data['old'])!=1:
                raise ValueError('Replacement must change exactly one matching occurrence')
            after=text.replace(data['old'],data['new'],1).encode('utf-8')
            if len(after)>1_000_000:raise ValueError('Result exceeds controller source-file capacity')
            after_hash=hashlib.sha256(after).hexdigest()
            # Canonical absolute identity shares the exclusion across aliases/tasks.
            path_key=os.path.normcase(str(path))
            with self.service.store.transaction() as db:
                session.tool_started('implementer','replace',request['operation_id'])
                if db.execute("SELECT 1 FROM broker_write_requests WHERE path_key=? AND status='inflight'",(path_key,)).fetchone():
                    raise PolicyDenied('Path has an unresolved prior write; operator inspection required')
                db.execute('INSERT INTO broker_write_requests VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                    (principal_id,request['operation_id'],fingerprint,session.run_id,path_key,data['path'],'inflight',expected,after_hash))
                self.service.store._event(db,session.run_id,request['operation_id'],'broker_write_intent',
                    {'path':data['path'],'before_sha256':expected,'after_sha256':after_hash})
            try:
                # Reuse exact uniqueness, Python AST, static audit and protected-path checks.
                ws.replace(data['path'],data['old'],data['new'],expected_sha256=expected)
                if hashlib.sha256(path.read_bytes()).hexdigest()!=after_hash:
                    raise GovernanceUnavailable('Replacement post-write hash mismatch')
                response={'ok':True,'result':{'authority':'controller executed replacement',
                    'operation_id':request['operation_id'],'path':data['path'],
                    'before_sha256':expected,'after_sha256':after_hash,'historical_response':False}}
            except Exception as error:
                if ws.effect_attempted:
                    raise GovernanceUnavailable('Replacement may have executed; no implicit retry or rollback') from error
                response={'ok':False,'error_type':'PolicyDenied' if isinstance(error,PolicyDenied) else 'ValueError',
                          'message':'Replacement rejected before write: '+type(error).__name__}
            with self.service.store.transaction() as db:
                self.service.store._event(db,session.run_id,request['operation_id'],'broker_write_outcome',
                    {'path':data['path'],'completed':response['ok'],'after_sha256':after_hash if response['ok'] else None})
                db.execute("UPDATE broker_write_requests SET status='complete',response=? WHERE principal=? AND operation_id=?",
                           (encoded(response),principal_id,request['operation_id']))
            return response
        finally:
            try:
                if ledger is not None:ledger.close()
            finally:
                try:locks.close()
                finally:self.read.slot.release()

    def inspect(self,principal_id,run_id,operation_id):
        if not isinstance(operation_id,str) or not 0<len(operation_id)<=256:raise ValueError('Invalid write operation ID')
        principal=self.service.principals[principal_id]
        with self.service.store.transaction() as db:
            self.service._session(db,principal,run_id)
            row=db.execute('SELECT * FROM broker_write_requests WHERE principal=? AND operation_id=? AND run_id=?',
                           (principal_id,operation_id,run_id)).fetchone()
            if row is None:raise PolicyDenied('Write record unavailable')
            value={key:row[key] for key in ('operation_id','path','status','before_hash','after_hash')}
        value['replay_authorized']=False
        return value

    def resolution_plan(self,principal_id,run_id,operation_id):
        """Trusted controller-only observation; not an automatic decision."""
        principal=self.service.principals[principal_id]
        with self.service.store.transaction() as db:
            self.service._session(db,principal,run_id)
            row=db.execute('SELECT * FROM broker_write_requests WHERE principal=? AND operation_id=? AND run_id=?',
                           (principal_id,operation_id,run_id)).fetchone()
            if row is None or row['status']!='inflight':raise PolicyDenied('No unresolved write for this run')
        path=self._approved_path(principal,row)
        with self._path_lock(path):
            current=hashlib.sha256(path.read_bytes()).hexdigest()
        return {'version':1,'principal':principal_id,'run_id':run_id,'operation_id':operation_id,
                'request_hash':row['request_hash'],'path':row['path'],'before_hash':row['before_hash'],
                'after_hash':row['after_hash'],'observed_sha256':current}

    def resolve(self,plan,*,decision,operator,reason,quiesced=False):
        """Trusted local adjudication. Does not modify source or replay work."""
        keys={'version','principal','run_id','operation_id','request_hash','path','before_hash','after_hash','observed_sha256'}
        if not isinstance(plan,dict) or set(plan)!=keys or type(plan['version']) is not int or plan['version']!=1:
            raise ValueError('Expected exact resolution plan')
        if any(not isinstance(plan[key],str) or not plan[key] or len(plan[key])>1024 for key in keys-{'version'}):
            raise ValueError('Invalid resolution plan fields')
        if decision not in ('applied','no_effect') or quiesced is not True:
            raise ValueError('Explicit decision and stopped-worker acknowledgement required')
        for value in (operator,reason):
            if not isinstance(value,str) or not value.strip() or len(value)>1024:
                raise ValueError('Operator identity and bounded nonempty reason required')
        identity=hashlib.sha256(encoded({'plan':plan,'decision':decision,'operator':operator,'reason':reason}).encode()).hexdigest()
        principal=self.service.principals[plan['principal']]
        with self.service.store.transaction() as db:
            self.service._session(db,principal,plan['run_id'])
            prior=db.execute('SELECT * FROM broker_write_resolutions WHERE principal=? AND operation_id=?',
                             (plan['principal'],plan['operation_id'])).fetchone()
            if prior:
                if prior['identity']!=identity:raise PolicyDenied('Conflicting write adjudication')
                result=json.loads(prior['response']);result['historical_response']=True
                return result
            row=db.execute('SELECT * FROM broker_write_requests WHERE principal=? AND operation_id=? AND run_id=?',
                           (plan['principal'],plan['operation_id'],plan['run_id'])).fetchone()
            if (not row or row['status']!='inflight'
                    or any(row[key]!=plan[key] for key in ('request_hash','path','before_hash','after_hash'))):
                raise PolicyDenied('Resolution plan no longer matches unresolved write')
        path=self._approved_path(principal,row)
        with self._path_lock(path):
            current=hashlib.sha256(path.read_bytes()).hexdigest()
            expected=plan['after_hash'] if decision=='applied' else plan['before_hash']
            if current!=plan['observed_sha256'] or current!=expected:
                raise PolicyDenied('File changed or decision conflicts with source; leave write unresolved')
            with self.service.store.transaction() as db:
                # Fence an old worker waiting for the file lock before publishing resolution.
                prior=db.execute('SELECT * FROM broker_write_resolutions WHERE principal=? AND operation_id=?',
                                 (plan['principal'],plan['operation_id'])).fetchone()
                if prior:
                    if prior['identity']!=identity:raise PolicyDenied('Conflicting write adjudication')
                    result=json.loads(prior['response']);result['historical_response']=True
                    return result
                current_row=db.execute('SELECT * FROM broker_write_requests WHERE principal=? AND operation_id=?',
                                       (plan['principal'],plan['operation_id'])).fetchone()
                if current_row['status']!='inflight' or current_row['request_hash']!=plan['request_hash']:
                    raise PolicyDenied('Write changed during adjudication; inspect again')
                db.execute("UPDATE governance_runs SET status='failed' WHERE id=?",(plan['run_id'],))
                db.execute("UPDATE governance_requests SET status='unknown' WHERE run_id=? AND status='dispatched'",(plan['run_id'],))
                response={'ok':False,'error_type':'PolicyDenied',
                          'message':'Write adjudicated by operator; original run revoked. Start a new authorized attempt.'}
                # Always refuse old worker continuation, even for an applied effect.
                db.execute("UPDATE broker_write_requests SET status='complete',response=? WHERE principal=? AND operation_id=?",
                           (encoded(response),plan['principal'],plan['operation_id']))
                result={'operation_id':plan['operation_id'],'decision':decision,'observed_sha256':current,
                        'authority':'trusted operator adjudication, not proof of original execution',
                        'original_run_revoked':True,'path_exclusion_released':True,
                        'replay_authorized':False,'historical_response':False}
                self.service.store._event(db,plan['run_id'],plan['operation_id'],'operator_write_resolution',
                    {**result,'operator':operator,'reason':reason,'quiesced_acknowledged':True,'plan_sha256':identity})
                db.execute('INSERT INTO broker_write_resolutions VALUES(?,?,?,?)',
                           (plan['principal'],plan['operation_id'],identity,encoded(result)))
                return result
