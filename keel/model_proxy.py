"""Controller-owned model execution with durable intent and no effect replay."""
import hashlib
import json
import math
import threading
import time
import uuid

from .core import ModelError, PolicyDenied
from .governance import GovernanceUnavailable, encoded, reject_nonfinite


class ModelProxy:
    def __init__(self,service,config):
        if (not isinstance(config,dict) or not {'models'}<=config.keys()
                or set(config)-{'models','max_output','timeout_seconds','max_concurrent'}):
            raise ValueError('Invalid model proxy configuration')
        models=config['models']
        if not isinstance(models,dict) or not models:raise ValueError('Expected server model aliases')
        self.max_output=config.get('max_output',8192)
        self.timeout=config.get('timeout_seconds',20)
        concurrent=config.get('max_concurrent',2)
        if type(self.max_output) is not int or not 1<=self.max_output<=32768:raise ValueError('Invalid proxy output cap')
        if type(concurrent) is not int or not 1<=concurrent<=8:raise ValueError('Invalid proxy concurrency')
        if type(self.timeout) not in (int,float) or not math.isfinite(self.timeout) or not 0<self.timeout<=25:
            raise ValueError('Proxy provider timeout must be positive and at most 25 seconds')
        from .models import from_config
        self.models={};self.policy_hashes={}
        for alias,spec in models.items():
            if not isinstance(alias,str) or not alias or len(alias)>128:raise ValueError('Invalid server model alias')
            if not isinstance(spec,dict) or spec.get('provider') not in {'openai-compatible','ollama'}:
                raise ValueError('Proxy requires a concrete supported server provider')
            self.models[alias]=from_config(spec)
            self.policy_hashes[alias]=hashlib.sha256(encoded({'model':spec,'max_output':self.max_output,
                                                             'timeout_seconds':self.timeout}).encode()).hexdigest()
            check=getattr(self.models[alias],'check_credentials',None)
            if callable(check):check()  # Local credential preflight only; no provider request.
        self.service=service;self.slots=threading.BoundedSemaphore(concurrent)
        self.stopping=threading.Event();self.lifecycle_lock=threading.Lock();self.active={}
        with service.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS proxy_model_requests (
                principal TEXT NOT NULL, operation_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                run_id TEXT NOT NULL, request_id TEXT NOT NULL, status TEXT NOT NULL,
                response TEXT, PRIMARY KEY(principal,operation_id))''')

    def execute(self,principal_id,request):
        principal=self.service.principals[principal_id]
        if (not isinstance(request,dict) or set(request)!={'operation_id','action','run_id','data'}
                or request['action']!='model_complete' or not isinstance(request['operation_id'],str)
                or not 0<len(request['operation_id'])<=256):raise ValueError('Invalid model operation envelope')
        data=request['data']
        if not isinstance(data,dict) or set(data)!={'alias','messages','schema','max_output','timeout'}:
            raise ValueError('Invalid model request fields')
        alias=data['alias'];messages=data['messages'];schema=data['schema']
        if not isinstance(alias,str) or alias not in principal.get('models',[]) or alias not in self.models:
            raise PolicyDenied('Model alias is not granted')
        if (not isinstance(messages,list) or not messages or any(not isinstance(m,dict)
                or set(m)!={'role','content'} or m['role'] not in ('system','user','assistant')
                or not isinstance(m['content'],str) for m in messages)):
            raise ValueError('Proxy requires text role/content messages')
        if schema is not None and not isinstance(schema,dict):raise ValueError('Invalid model schema')
        limit=data['max_output'];timeout=data['timeout']
        if type(limit) is not int or not 0<limit<=self.max_output:raise ValueError('Model output exceeds server cap')
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
            raise ValueError('Invalid model timeout')
        raw=encoded(request).encode()
        if len(raw)>131072:raise ValueError('Model request exceeds control transport capacity')
        fingerprint=hashlib.sha256(raw+self.policy_hashes[alias].encode()).hexdigest()
        if not self.slots.acquire(blocking=False):raise GovernanceUnavailable('Proxy capacity unavailable; no provider dispatch')
        key=(principal_id,request['operation_id']);registered=False
        try:
            with self.service.store.transaction() as db:
                session=self.service._session(db,principal,request['run_id'])
                prior=db.execute('SELECT * FROM proxy_model_requests WHERE principal=? AND operation_id=?',
                                 (principal_id,request['operation_id'])).fetchone()
                if prior:
                    if prior['request_hash']!=fingerprint:raise PolicyDenied('Model operation ID changed input')
                    if prior['status']=='complete':return json.loads(prior['response'])
                    # In-flight and crashed requests are deliberately indistinguishable.
                    raise GovernanceUnavailable('Provider outcome unconfirmed; external call will not be replayed')
                session._active(db)
                with self.lifecycle_lock:
                    if self.stopping.is_set():raise GovernanceUnavailable('Model proxy stopping; no new provider dispatch')
                    self.active[key]={'principal':principal_id,'operation_id':request['operation_id'],
                                      'run_id':session.run_id,'alias':alias,'phase':'preparing'}
                    registered=True
                deadline=self.service.store.runs.get_bound(session._run_grant()).deadline
                timeout=min(timeout,self.timeout,deadline-self.service.store.clock())
                if timeout<=0:raise PolicyDenied('Run lease expired')
                estimate=len(encoded({'messages':messages,'schema':schema}).encode())+limit
                request_id='proxy-'+uuid.uuid4().hex
                session.reserve(estimate,request_id=request_id)
                db.execute('INSERT INTO proxy_model_requests VALUES(?,?,?,?,?,?,NULL)',
                           (principal_id,request['operation_id'],fingerprint,session.run_id,request_id,'inflight'))
            with self.lifecycle_lock:self.active[key].update(request_id=request_id,phase='intent_committed')
            # No database write transaction is held during a provider/network call.
            actual=None
            try:
                if self.stopping.is_set():
                    # No provider adapter has been entered: zero dispatch is known.
                    raise ModelError('Shutdown before provider adapter dispatch',tokens=0)
                with self.lifecycle_lock:self.active[key]['phase']='provider_call'
                model=self.models[alias]
                reply=(model.complete_json(messages,schema=schema,timeout=timeout,max_output=limit)
                       if schema is not None else model.complete(messages,timeout=timeout,max_output=limit))
                actual=reply.tokens if type(reply.tokens) is int and reply.tokens>=0 else None
                if actual is None:raise ModelError('Provider did not return usable accounting')
                if not isinstance(reply.content,str):raise ModelError('Provider returned invalid content')
                if schema is not None:json.loads(reply.content,parse_constant=reject_nonfinite)
                if actual>estimate:raise ModelError('Provider usage exceeded reservation; inspect counting policy')
                response={'ok':True,'result':{'content':reply.content,'tokens':actual,
                    'metadata':{'provider':'control-proxy','alias':alias,'usage_authority':'controller provider adapter'}}}
                if len(encoded(response).encode())>240000:raise ModelError('Model reply exceeds control transport capacity')
            except Exception as error:
                known=getattr(error,'tokens',None)
                if type(known) is int and known>=0:actual=known
                # Provider exception strings can contain sensitive data; do not relay them.
                response={'ok':False,'error_type':'ModelError','message':'Controller provider call failed: '+type(error).__name__,
                          'tokens':actual}
            with self.lifecycle_lock:self.active[key]['phase']='settling'
            with self.service.store.transaction() as db:
                session.settle(request_id,actual,outcome='completed' if response['ok'] else 'provider_error')
                db.execute("UPDATE proxy_model_requests SET status='complete',response=? WHERE principal=? AND operation_id=?",
                           (encoded(response),principal_id,request['operation_id']))
            return response
        finally:
            if registered:
                with self.lifecycle_lock:self.active.pop(key,None)
            self.slots.release()

    def request_stop(self):
        with self.lifecycle_lock:self.stopping.set()

    def inspect(self,principal_id,run_id,operation_id):
        if not isinstance(operation_id,str) or not 0<len(operation_id)<=256:raise ValueError('Invalid model operation ID')
        principal=self.service.principals[principal_id]
        with self.service.store.transaction() as db:
            self.service._session(db,principal,run_id)
            row=db.execute('''SELECT p.operation_id,p.request_id,p.status,g.reserved,g.actual,g.status AS usage_status
                FROM proxy_model_requests p JOIN governance_requests g ON p.request_id=g.id
                WHERE p.principal=? AND p.run_id=? AND p.operation_id=?''',(principal_id,run_id,operation_id)).fetchone()
            if row is None:raise PolicyDenied('Model request unavailable')
        return {**dict(row),'replay_authorized':False,'provider_cancellation_confirmed':False,
                'scope':'Controller operation/usage records, not independent provider billing evidence'}

    def shutdown(self,*,timeout=10):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=30:
            raise ValueError('Provider drain budget must be positive and at most 30 seconds')
        deadline=time.monotonic()+timeout;self.request_stop()
        while time.monotonic()<deadline:
            with self.lifecycle_lock:
                if not self.active:break
            time.sleep(min(.02,max(.001,deadline-time.monotonic())))
        with self.lifecycle_lock:active=[dict(value) for value in self.active.values()]
        with self.service.store.transaction() as db:
            inflight=db.execute("SELECT COUNT(*) FROM proxy_model_requests WHERE status='inflight'").fetchone()[0]
            unknown=db.execute("SELECT COUNT(*) FROM proxy_model_requests p JOIN governance_requests g ON p.request_id=g.id WHERE g.status='unknown'").fetchone()[0]
            rows=db.execute('''SELECT p.principal,p.run_id,p.operation_id,p.request_id,p.status,g.status AS usage_status
                FROM proxy_model_requests p JOIN governance_requests g ON p.request_id=g.id
                WHERE p.status='inflight' OR g.status='unknown' ORDER BY p.operation_id LIMIT 32''').fetchall()
        confirmed=not active and inflight==0 and unknown==0
        return {'status':'stopped' if confirmed else 'cleanup_unconfirmed','current_calls_drained':not active,
                'active':active,'persisted_inflight_records':inflight,'unknown_usage_records':unknown,
                'unconfirmed_record_preview':[dict(row) for row in rows],
                'provider_cancellation_attempted':False,'unknown_reservations_released':False,
                'scope':'Bounded provider drain; includes historical uncertainty, not remote cancellation or billing certification'}


class ProxyModel:
    """Runtime model boundary; provider credentials exist only on the controller."""
    def __init__(self,alias):
        if not isinstance(alias,str) or not alias:raise ValueError('Proxy alias required')
        self.alias=alias;self.session=None

    def bind_governance(self,session):
        from .remote_governance import RemoteSession
        if not isinstance(session,RemoteSession):raise ValueError('Control proxy requires remote governance')
        if self.session is not None and self.session is not session:raise PolicyDenied('Proxy already bound to a session')
        self.session=session

    def complete(self,messages,*,timeout,max_output):return self._call(messages,None,timeout,max_output)

    def complete_json(self,messages,*,schema,timeout,max_output):return self._call(messages,schema,timeout,max_output)

    def _call(self,messages,schema,timeout,max_output):
        if self.session is None:raise PolicyDenied('Proxy requires authenticated remote governance before dispatch')
        from .models import Reply
        result=self.session._rpc('model_complete',{'alias':self.alias,'messages':messages,'schema':schema,
                                                 'timeout':timeout,'max_output':max_output})
        return Reply(result['content'],result['tokens'],result['metadata'])
