"""Asynchronous fixed Docker acceptance; no client-supplied commands or replay."""
import base64
from contextlib import ExitStack
import hashlib
import json
import math
import threading
import time
import uuid

from compass.progress import ProgressLog, atomic_json
from .core import Budget, Ledger, Limits, PolicyDenied, Trace, digest
from .execution import CommandRunner, normalize_acceptance, validate_execution
from .governance import GovernanceUnavailable, encoded
from .workspace import Workspace
from .container_receipts import ContainerRegistry, TrackedCommandRunner


class VerificationWorkspace(Workspace):
    def files(self):
        for name,path in super().files():
            self.budget.check()
            yield name,path


class ExecutionBroker:
    def __init__(self,service,config):
        if not isinstance(config,dict) or set(config)!={'tasks'} or not isinstance(config['tasks'],dict):
            raise ValueError('Execution broker requires fixed tasks')
        if service.read_broker is None:raise ValueError('Execution broker requires controller repository bindings')
        self.service=service;self.tasks={};self.policy_hashes={}
        for task,spec in config['tasks'].items():
            if (task not in service.read_broker.repositories or not isinstance(spec,dict)
                    or set(spec)!={'execution','acceptance','max_seconds'}):raise ValueError('Invalid fixed acceptance task')
            validate_execution(spec['execution'])
            image=spec['execution'].get('image','')
            image_hash=image.removeprefix('sha256:') if image.startswith('sha256:') else image.rsplit('@sha256:',1)[-1]
            if (spec['execution'].get('backend')!='docker' or len(image_hash)!=64
                    or any(c not in '0123456789abcdef' for c in image_hash)
                    or not (image.startswith('sha256:') or '@sha256:' in image)):
                raise ValueError('Acceptance requires immutable Docker image identity')
            seconds=spec['max_seconds']
            if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<seconds<=600:
                raise ValueError('Acceptance budget must be positive and at most 600 seconds')
            normalized=normalize_acceptance(spec['acceptance'])
            if not all(entry['junit'] for entry in normalized):
                raise ValueError('First execution broker requires JUnit-enabled fixed acceptance')
            self.tasks[task]={**spec,'acceptance':normalized}
            self.policy_hashes[task]=digest(self.tasks[task])
        self.slots=threading.BoundedSemaphore(1);self.active=set();self.lock=threading.Lock()
        self.owner=uuid.uuid4().hex;self.stopping=threading.Event();self.threads={}
        self.containers=ContainerRegistry(service.store,self.owner)
        with service.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS broker_verifications (
                id TEXT PRIMARY KEY, principal TEXT NOT NULL, operation_id TEXT NOT NULL,
                run_id TEXT NOT NULL, request_hash TEXT NOT NULL, status TEXT NOT NULL,
                receipt TEXT, UNIQUE(principal,operation_id))''')

    def capability(self,principal):
        spec=self.tasks.get(principal['task_id'])
        if spec and 'verify' in principal['tools'].get('verifier',[]):
            return {'acceptance_sha256':digest(spec['acceptance']),'policy_sha256':self.policy_hashes[principal['task_id']],
                    'max_seconds':spec['max_seconds']}
        return None

    def operate(self,principal_id,request):
        if not isinstance(request,dict) or set(request)!={'operation_id','action','run_id','data'}:
            raise ValueError('Invalid verification envelope')
        if not isinstance(request['operation_id'],str) or not 0<len(request['operation_id'])<=256:
            raise ValueError('Invalid verification operation ID')
        principal=self.service.principals[principal_id]
        if not self.capability(principal):raise PolicyDenied('Fixed acceptance not granted')
        if request['action']=='verify_start':return self._start(principal,request)
        if request['action'] not in {'verify_status','verify_page'}:raise ValueError('Invalid verification action')
        data=request['data'];keys={'job_id'} if request['action']=='verify_status' else {'job_id','offset'}
        if not isinstance(data,dict) or set(data)!=keys or not isinstance(data['job_id'],str):
            raise ValueError('Invalid verification query')
        with self.service.store.transaction() as db:
            self.service._session(db,principal,request['run_id'])
            row=db.execute('SELECT * FROM broker_verifications WHERE id=? AND principal=? AND run_id=?',
                           (data['job_id'],principal['id'],request['run_id'])).fetchone()
            if row is None:raise PolicyDenied('Verification job unavailable')
        if request['action']=='verify_status':
            with self.lock:active=row['id'] in self.active
            return {'ok':True,'result':{'job_id':row['id'],'status':row['status'] if row['status']!='running' or active else 'unknown',
                                       'receipt':json.loads(row['receipt']) if row['receipt'] else None}}
        offset=data['offset']
        if type(offset) is not int or offset<0 or row['status']!='complete':raise ValueError('Invalid result page request')
        path=self._folder(row['run_id'],row['id'])/'verification.json'
        with path.open('rb') as stream:
            stream.seek(offset);chunk=stream.read(65536)
        if not chunk:raise ValueError('Result offset outside artifact')
        return {'ok':True,'result':{'data_base64':base64.b64encode(chunk).decode(),
                                  'next_offset':offset+len(chunk) if offset+len(chunk)<path.stat().st_size else None}}

    def _folder(self,run_id,job_id):return self.service.read_broker.evidence/run_id/('verify-'+job_id)

    def _start(self,principal,request):
        if self.stopping.is_set():raise GovernanceUnavailable('Controller acceptance is stopping; no new dispatch')
        data=request['data'];spec=self.tasks[principal['task_id']]
        if not isinstance(data,dict) or set(data)!={'source_sha256','acceptance_sha256','timeout'}:
            raise ValueError('Fixed acceptance accepts source/hash/timeout only')
        if data['acceptance_sha256']!=digest(spec['acceptance']):raise PolicyDenied('Worker acceptance differs from fixed server contract')
        if not isinstance(data['source_sha256'],str) or len(data['source_sha256'])!=64:
            raise ValueError('Expected source snapshot fingerprint')
        timeout=data['timeout']
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:raise ValueError('Invalid worker remaining budget')
        fingerprint=digest([request,self.policy_hashes[principal['task_id']]])
        with self.service.store.transaction() as db:
            session=self.service._session(db,principal,request['run_id'])
            prior=db.execute('SELECT * FROM broker_verifications WHERE principal=? AND operation_id=?',
                             (principal['id'],request['operation_id'])).fetchone()
            if prior:
                if prior['request_hash']!=fingerprint:raise PolicyDenied('Verification operation ID changed input')
                return {'ok':True,'result':{'job_id':prior['id'],'historical_response':True}}
            if db.execute("SELECT 1 FROM broker_verifications WHERE run_id=? AND status='running'",(session.run_id,)).fetchone():
                raise GovernanceUnavailable('Run has an outstanding acceptance; reconcile its job instead of starting another')
        if not self.slots.acquire(blocking=False):raise GovernanceUnavailable('Acceptance executor busy; no dispatch')
        handed_off=False;job_id=uuid.uuid4().hex
        try:
            with self.service.store.transaction() as db:
                session.tool_started('verifier','verify',request['operation_id'])
                db.execute('INSERT INTO broker_verifications VALUES(?,?,?,?,?,?,NULL)',
                           (job_id,principal['id'],request['operation_id'],session.run_id,fingerprint,'running'))
                run=db.execute('SELECT deadline FROM governance_runs WHERE id=?',(session.run_id,)).fetchone()
                timeout=min(timeout,spec['max_seconds'],max(.01,run['deadline']-self.service.store.clock()))
            thread=threading.Thread(target=self._run,args=(principal,session,job_id,data['source_sha256'],timeout),daemon=True)
            with self.lock:
                if self.stopping.is_set():raise GovernanceUnavailable('Controller acceptance stopped before thread launch')
                self.active.add(job_id);self.threads[job_id]=thread
                thread.start();handed_off=True
            return {'ok':True,'result':{'job_id':job_id,'historical_response':False}}
        finally:
            if not handed_off:
                with self.lock:self.active.discard(job_id);self.threads.pop(job_id,None)
                self.slots.release()

    def _run(self,principal,session,job_id,expected,timeout):
        ledger=None;receipt=None;status='unavailable'
        folder=self._folder(session.run_id,job_id)
        try:
            if self.stopping.is_set():raise GovernanceUnavailable('Controller acceptance stopping')
            folder.mkdir(parents=True,exist_ok=False)
            spec=self.tasks[principal['task_id']];read=self.service.read_broker
            root=read.repositories[principal['task_id']]['root']
            budget=Budget(Limits(max_wallclock=timeout,max_tool_calls=max(1,len(spec['acceptance']))))
            ledger=Ledger(folder/'ledger.sqlite')
            ws=VerificationWorkspace(root,budget,ledger,Trace(folder/'trace.jsonl'),
                runner=TrackedCommandRunner(spec['execution'],self.containers,job_id,self.stopping))
            with ProgressLog(folder/'progress.jsonl',interval=5) as progress, ExitStack() as locks:
                progress.emit('source_binding',job_id=job_id)
                # Coordinate with compliant replacements; no control DB transaction during tests.
                for name in sorted(read.repositories[principal['task_id']]['writable_files']):
                    path=Workspace.path(ws,name,write=True)
                    locks.enter_context(self.service.write_broker._path_lock(path))
                before=ws.snapshot()
                atomic_json(folder/'source-binding.json',{'requested_sha256':expected,'observed_sha256':digest(before),'files':before})
                if digest(before)!=expected:raise PolicyDenied('Controller source differs from requested candidate')
                from .verification_infrastructure import docker_health, EnvironmentBlocked
                health=docker_health(timeout=min(5,max(.1,budget.remaining)))
                atomic_json(folder/'docker-health.json',health)
                if not health.get('ready'):raise EnvironmentBlocked('Docker unavailable; no acceptance dispatch')
                progress.emit('acceptance_started',commands=len(spec['acceptance']))
                rows=ws.verify(spec['acceptance'],phase='controller')
                if (len(rows)!=len(spec['acceptance']) or any(row.get('timeout') or row.get('metadata_error')
                        or not isinstance(row.get('metadata'),dict) for row in rows)):
                    raise EnvironmentBlocked('Acceptance did not establish complete test evidence')
                if ws.snapshot()!=before:raise PolicyDenied('Source changed during controller acceptance')
                payload={'authority':'controller executed fixed Docker acceptance','source_sha256':expected,
                         'acceptance_sha256':digest(spec['acceptance']),'verification':rows,'job_id':job_id}
                atomic_json(folder/'verification.json',payload)
                raw=(folder/'verification.json').read_bytes()
                receipt={'result_sha256':hashlib.sha256(raw).hexdigest(),'result_bytes':len(raw),
                         'source_sha256':expected,'acceptance_sha256':digest(spec['acceptance'])}
                status='complete';progress.emit('acceptance_recorded',result_sha256=receipt['result_sha256'])
        except Exception as error:
            receipt={'error_type':type(error).__name__,'message':'Fixed acceptance unavailable; inspect controller artifacts'}
        finally:
            try:
                if ledger is not None:ledger.close()
                cleanup=self.containers.inspect_job(job_id,remove=True,timeout=5)
                if not cleanup['confirmed_absent']:
                    status='cleanup_unconfirmed'
                    receipt={'prior_result':receipt,'cleanup':cleanup}
                elif self.stopping.is_set():
                    status='unavailable';receipt={'message':'Controller shutdown cancelled acceptance','cleanup':cleanup}
                elif isinstance(receipt,dict):receipt['cleanup']=cleanup
                with self.service.store.transaction() as db:
                    self.service.store._event(db,session.run_id,job_id,'broker_verification_outcome',{'status':status,'receipt':receipt})
                    db.execute('UPDATE broker_verifications SET status=?,receipt=? WHERE id=?',(status,encoded(receipt),job_id))
            finally:
                with self.lock:self.active.discard(job_id);self.threads.pop(job_id,None)
                self.slots.release()

    def request_stop(self):
        with self.lock:self.stopping.set()

    def shutdown(self,*,timeout=10):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=30:
            raise ValueError('Shutdown budget must be positive and at most 30 seconds')
        deadline=time.monotonic()+timeout
        with self.lock:
            self.stopping.set();threads=dict(self.threads)
        observed={}
        while any(thread.is_alive() for thread in threads.values()) and time.monotonic()<deadline:
            for job,thread in threads.items():
                if thread.is_alive() and time.monotonic()<deadline:
                    observed[job]=self.containers.inspect_job(job,remove=True,timeout=min(2,max(.01,deadline-time.monotonic())))
                    thread.join(timeout=min(.05,max(.001,deadline-time.monotonic())))
        # Final observation after threads stop catches a container launched just
        # after a preceding 'absent' observation. Never infer cleanup from that race.
        with self.service.store.transaction() as db:
            rows=db.execute('SELECT DISTINCT job_id FROM broker_containers WHERE owner=?',(self.owner,)).fetchall()
            older=db.execute('SELECT COUNT(*) FROM broker_containers WHERE owner<>?',(self.owner,)).fetchone()[0]
        for row in rows:
            if time.monotonic()<deadline:
                observed[row['job_id']]=self.containers.inspect_job(row['job_id'],remove=True,
                    timeout=max(.01,deadline-time.monotonic()))
            else:observed[row['job_id']]={'confirmed_absent':False,'status':'not_checked_budget'}
        alive=[job for job,thread in threads.items() if thread.is_alive()]
        return {'status':'stopped' if not alive and all(r['confirmed_absent'] for r in observed.values()) else 'cleanup_unconfirmed',
                'owner_instance':self.owner,'threads_still_alive':alive,'jobs':observed,
                'older_owner_container_records_not_checked':older,
                'scope':'Current-instance acceptance threads and recorded containers only; no replay or daemon-wide cleanup'}
