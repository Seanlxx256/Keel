"""Bounded client for the separate governance service; no automatic RPC retry."""
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import base64
import hashlib
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

from .core import BudgetExceeded, PolicyDenied, ModelError
from .governance import GovernanceUnavailable, encoded


def loopback(host):
    if host == 'localhost':return True
    try:return ipaddress.ip_address(host).is_loopback
    except ValueError:return False


def validate_remote_config(config):
    required={'endpoint','token_env','task_id'}
    if not isinstance(config,dict) or not required <= config.keys() or set(config)-required-{'timeout_seconds','state_path'}:
        raise ValueError('Remote governance accepts endpoint, token_env, task_id, timeout_seconds and state_path only')
    if 'state_path' in config and (not isinstance(config['state_path'],str) or not config['state_path'].strip()):
        raise ValueError('state_path must be a nonempty trusted-host file path')
    if not isinstance(config['endpoint'],str):raise ValueError('endpoint must be a URL string')
    parsed=urlsplit(config['endpoint'])
    if (parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in {'','/'} or parsed.query or parsed.fragment):
        raise ValueError('Governance endpoint must be an HTTP(S) origin without credentials')
    if parsed.scheme=='http' and not loopback(parsed.hostname):
        raise ValueError('Non-loopback governance requires HTTPS')
    if not isinstance(config['token_env'],str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',config['token_env']):
        raise ValueError('token_env must name an environment variable')
    if not isinstance(config['task_id'],str) or not config['task_id'] or len(config['task_id'])>256:
        raise ValueError('task_id must be nonempty bounded text')
    timeout=config.get('timeout_seconds',3)
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=30:
        raise ValueError('Remote governance timeout must be finite, positive and at most 30 seconds')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class RemoteSession:
    def __init__(self,config):
        validate_remote_config(config)
        self.client_config=dict(config)
        self.config={}
        self.location=config['endpoint'].rstrip('/')
        self.run_id=None
        self.pending=None
        self.budget=None
        self._lock=threading.Lock()
        self.recovery_only=False
        self._storage_failed=False
        self.verification_job=None
        self.mcp_operation=None
        token=os.environ.get(config['token_env'],'')
        if not token or token!=token.strip() or len(token)<32:
            raise PolicyDenied('Remote governance credential missing or invalid')
        self._token=token

    @classmethod
    def begin(cls,config,identity,wallclock,*,budget=None):
        session=cls(config)
        session.budget=budget
        if config.get('state_path'):
            path=Path(config['state_path'])
            path.parent.mkdir(parents=True,exist_ok=True)
            # Exclusive creation prevents a new run from overwriting old intents.
            with path.open('x',encoding='utf-8') as stream:
                json.dump(session._snapshot(),stream)
        try:result=session._rpc('begin',{'task_id':config['task_id'],'identity':identity,'wallclock_seconds':wallclock})
        except GovernanceUnavailable as error:
            error.governance_session=session
            raise
        return session

    def _snapshot(self):
        return {'version':1,'endpoint':self.location,'task_id':self.client_config['task_id'],
                'run_id':self.run_id,'config':self.config,'pending':self.pending,
                'recovery_only':self.recovery_only,'verification_job':self.verification_job,'mcp_operation':self.mcp_operation}

    def _persist(self):
        if not self.client_config.get('state_path'):return
        try:
            from compass.progress import atomic_json
            atomic_json(Path(self.client_config['state_path']),self._snapshot())
        except Exception as error:
            self._storage_failed=True
            raise GovernanceUnavailable('Required client checkpoint write failed; stop this session') from error

    @classmethod
    def recover(cls,config,*,budget=None):
        """Recover control RPCs only. Never resume a model/tool side effect."""
        session=cls(config)
        if not config.get('state_path'):raise ValueError('Recovery requires state_path')
        path=Path(config['state_path'])
        if path.stat().st_size>262144:raise ValueError('Client checkpoint exceeds bound')
        value=json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(value,dict) or value.get('version')!=1
                or value.get('endpoint')!=session.location or value.get('task_id')!=config['task_id']
                or not isinstance(value.get('config'),dict)
                or (value.get('run_id') is not None and not isinstance(value['run_id'],str))):
            raise ValueError('Client checkpoint identity or format mismatch')
        pending=value.get('pending')
        if pending is not None:
            if (not isinstance(pending,dict) or not isinstance(pending.get('operation_id'),str)
                    or not isinstance(pending.get('data'),dict)
                    or pending.get('action') not in {'begin','reserve','settle','finish','event','tool_started','report','inspect',
                                                    'queue_claim','queue_start','queue_finish','queue_renew','queue_status','model_complete','tool_read',
                                                    'tool_replace','tool_write_status','verify_start','verify_status','verify_page','mcp_call','mcp_page','mcp_preflight'}
                    or pending.get('run_id')!=value.get('run_id')):
                raise ValueError('Invalid pending control operation')
        if value.get('run_id') is None and (pending is None or pending['action']!='begin'):
            raise ValueError('Checkpoint has no recoverable run or begin intent')
        session.run_id=value['run_id'];session.config=value['config'];session.pending=pending
        job=value.get('verification_job')
        if job is not None and (not isinstance(job,str) or len(job)!=32):raise ValueError('Invalid verification job checkpoint')
        session.verification_job=job
        operation=value.get('mcp_operation')
        if operation is not None and (not isinstance(operation,str) or not 0<len(operation)<=256):raise ValueError('Invalid MCP operation checkpoint')
        session.mcp_operation=operation
        session.budget=budget;session.recovery_only=True
        session._persist()
        return session

    def _completed(self,action,result):
        if action=='begin':
            self.run_id=result['run_id']
            self.config={'scope':result['scope'],'lease_seconds':result['lease_seconds']}
            if result.get('read_broker') is not None:self.config['read_broker']=result['read_broker']
            if result.get('write_broker') is not None:self.config['write_broker']=result['write_broker']
            if result.get('execution_broker') is not None:self.config['execution_broker']=result['execution_broker']
            if result.get('mcp_broker') is not None:self.config['mcp_broker']=result['mcp_broker']
        if action=='verify_start':self.verification_job=result['job_id']
        if action=='mcp_call':self.mcp_operation=result['operation_id']
        self.pending=None
        self._persist()

    def _send(self,operation):
        raw=encoded(operation).encode('utf-8')
        if len(raw)>131072:raise ValueError('Control request too large; send artifact references')
        request=urllib.request.Request(self.location+'/v1/operation',data=raw,
            headers={'Content-Type':'application/json','Authorization':'Bearer '+self._token},method='POST')
        try:
            # Do not leak credentials through inherited proxies or redirects.
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
            timeout=self.client_config.get('timeout_seconds',3)
            if operation.get('action') in {'model_complete','mcp_call','mcp_preflight'}:
                requested=operation['data']['timeout']
                if type(requested) not in (int,float) or not math.isfinite(requested) or requested<=0:
                    raise ValueError('Invalid proxy model timeout')
                # Bounded response headroom beyond the server's <=25s call cap.
                timeout=min(30,max(timeout,min(25,requested)+3))
            if self.budget is not None:timeout=min(timeout,max(.1,self.budget.remaining))
            with opener.open(request,timeout=timeout) as response:
                payload=response.read(262145)
            if len(payload)>262144:raise ValueError('Control response exceeds bound')
            value=json.loads(payload)
            if not isinstance(value,dict) or type(value.get('ok')) is not bool:raise ValueError('Invalid control envelope')
        except urllib.error.HTTPError as error:
            status=error.code;error.close()
            if status in {301,302,303,307,308,401,403}:raise PolicyDenied('Control authentication or redirect denied') from None
            if status in {400,404,413}:raise ValueError('Control protocol request rejected: HTTP '+str(status)) from None
            raise GovernanceUnavailable('Control HTTP response unavailable; operation '+operation['operation_id']) from None
        except (urllib.error.URLError,OSError,ValueError) as error:
            raise GovernanceUnavailable('Control response unavailable; operation '+operation['operation_id']+
                ' remains unconfirmed ('+type(error).__name__+')') from None
        if not value['ok']:
            kind=value.get('error_type')
            if kind in {'McpToolError','McpTransportUnavailable'}:
                from .mcp_client import McpToolError, McpTransportUnavailable
                error=(McpTransportUnavailable if kind=='McpTransportUnavailable' else McpToolError)(value.get('message','Controller MCP failed'))
                if isinstance(value.get('failure'),dict):error.failure=value['failure']
                raise error
            if kind=='ModelError':raise ModelError(value.get('message','Controller model call failed'),tokens=value.get('tokens'))
            error={'BudgetExceeded':BudgetExceeded,'PolicyDenied':PolicyDenied,'ValueError':ValueError}.get(kind,GovernanceUnavailable)
            raise error(value.get('message','Control operation rejected'))
        return value['result']

    def _rpc(self,action,data):
        with self._lock:
            return self._rpc_locked(action,data)

    def _rpc_locked(self,action,data):
        if self._storage_failed:raise GovernanceUnavailable('Client checkpoint failed; recover from disk before continuing')
        if self.recovery_only and action not in {'report','inspect','finish','queue_status','tool_write_status','verify_status','verify_page','mcp_page'}:
            raise GovernanceUnavailable('Recovered session permits inspection and closure only; no new external actions')
        if self.budget is not None and action in {'begin','reserve','tool_started','queue_claim','queue_start','queue_renew','model_complete','tool_read','tool_replace','verify_start','mcp_call','mcp_preflight'}:self.budget.check()
        if self.pending is not None:
            raise GovernanceUnavailable('Unconfirmed control operation; reconcile the exact operation before new work')
        operation={'operation_id':uuid.uuid4().hex,'action':action,'data':data}
        if self.run_id is not None:operation['run_id']=self.run_id
        self.pending=operation
        self._persist()
        try:
            result=self._send(operation)
        except GovernanceUnavailable:
            raise
        except BaseException:
            self.pending=None
            self._persist()
            raise
        self._completed(action,result)
        return result

    def reconcile_pending(self):
        """Repeat the exact RPC ID, not the model/tool action it authorized."""
        with self._lock:
            return self._reconcile_locked()

    def _reconcile_locked(self):
        if self._storage_failed:raise GovernanceUnavailable('Recover the last durable checkpoint with a new client')
        if self.pending is None:raise ValueError('No unconfirmed operation')
        action=self.pending['action']
        try:result=self._send(self.pending)
        except GovernanceUnavailable:raise
        except BaseException:
            self.pending=None
            self._persist()
            raise
        self._completed(action,result)
        return result

    def event(self,kind,payload,*,action_id=None):
        return self._rpc('event',{'kind':kind,'payload':payload,'action_id':action_id or uuid.uuid4().hex})

    def tool_started(self,role,tool,action_id):
        return self._rpc('tool_started',{'role':role,'tool':tool,'action_id':action_id})

    def read_tool(self,role,tool,args):return self._rpc('tool_read',{'role':role,'tool':tool,'args':args})

    def replace_tool(self,path,old,new,before_sha256):
        return self._rpc('tool_replace',{'path':path,'old':old,'new':new,'before_sha256':before_sha256})

    def write_status(self,operation_id):return self._rpc('tool_write_status',{'write_operation_id':operation_id})

    def inspect_pending_write(self):
        """Read-only control query preserving the original uncertain write intent."""
        with self._lock:
            if self.pending is None or self.pending['action']!='tool_replace':
                raise ValueError('No pending replacement to inspect')
            return self._send({'operation_id':uuid.uuid4().hex,'action':'tool_write_status',
                              'run_id':self.pending['run_id'],
                              'data':{'write_operation_id':self.pending['operation_id']}})

    def verification_status(self,job_id):return self._rpc('verify_status',{'job_id':job_id})

    def verification_page(self,job_id,offset):return self._rpc('verify_page',{'job_id':job_id,'offset':offset})

    def verify_commands(self,source_sha256,acceptance_sha256,timeout):
        from .verification_infrastructure import EnvironmentBlocked
        deadline=time.monotonic()+timeout
        result=self._rpc('verify_start',{'source_sha256':source_sha256,'acceptance_sha256':acceptance_sha256,'timeout':timeout})
        job=result['job_id']
        while True:
            if self.budget is not None:self.budget.check()
            if time.monotonic()>=deadline:raise EnvironmentBlocked('Controller acceptance response deadline; job retained, no repeat dispatch')
            status=self.verification_status(job)
            if status['status']=='complete':break
            if status['status']!='running':raise EnvironmentBlocked('Controller acceptance unavailable/unknown; inspect retained job')
            time.sleep(min(1,max(.01,deadline-time.monotonic())))
        receipt=status['receipt']
        raw=self._collect_artifact(lambda offset:self.verification_page(job,offset),receipt['result_bytes'],receipt['result_sha256'],deadline)
        payload=json.loads(raw)
        if (payload.get('authority')!='controller executed fixed Docker acceptance'
                or payload.get('source_sha256')!=source_sha256 or payload.get('acceptance_sha256')!=acceptance_sha256):
            raise PolicyDenied('Verification artifact has mismatched authority/source/contract')
        return payload

    def _collect_artifact(self,fetch,size,expected_hash,deadline):
        from .verification_infrastructure import EnvironmentBlocked
        chunks=[];offset=0;received=0
        if type(size) is not int or size<=0:raise PolicyDenied('Invalid controller artifact size')
        while offset is not None:
            if self.budget is not None:self.budget.check()
            if time.monotonic()>=deadline:raise EnvironmentBlocked('Result transfer deadline; complete controller artifact retained')
            page=fetch(offset)
            chunk=base64.b64decode(page['data_base64'],validate=True)
            if not chunk or len(chunk)>65536:raise PolicyDenied('Invalid verification artifact page')
            chunks.append(chunk)
            received+=len(chunk)
            next_offset=page['next_offset']
            if next_offset is not None and (type(next_offset) is not int or next_offset!=offset+len(chunk)):
                raise PolicyDenied('Invalid verification page continuation')
            offset=next_offset
            if received>size:raise PolicyDenied('Controller artifact exceeds declared size')
        raw=b''.join(chunks)
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=expected_hash:raise PolicyDenied('Controller artifact hash mismatch')
        return raw

    def preflight_mcp(self,timeout):
        result=self._rpc('mcp_preflight',{'timeout':timeout})
        if result.get('authority')!='controller host capability probe' or result.get('run_id')!=self.run_id:
            raise PolicyDenied('MCP preflight authority/run mismatch')
        return result

    def mcp_page(self,operation_id,offset):return self._rpc('mcp_page',{'target_operation_id':operation_id,'offset':offset})

    def call_mcp(self,role,alias,arguments,source_sha256,timeout):
        deadline=time.monotonic()+timeout
        receipt=self._rpc('mcp_call',{'role':role,'alias':alias,'arguments':arguments,'source_sha256':source_sha256,'timeout':timeout})
        operation=receipt['operation_id']
        raw=self._collect_artifact(lambda offset:self.mcp_page(operation,offset),receipt['artifact_bytes'],
                                   receipt['artifact_sha256'],deadline)
        payload=json.loads(raw)
        if payload.get('operation_id')!=operation or payload.get('source_sha256')!=source_sha256:
            raise PolicyDenied('MCP artifact provenance mismatch')
        return payload

    def cancel_pending_mcp(self):
        """Out-of-band cancellation: preserve the original locked/pending call."""
        # Snapshot the immutable operation object without waiting behind the
        # blocking RPC lock. Server checks exact principal/run/target binding.
        pending=self.pending
        if pending is None or pending['action']!='mcp_call':raise ValueError('No pending MCP invocation')
        return self._send({'operation_id':uuid.uuid4().hex,'action':'mcp_cancel','run_id':pending['run_id'],
                          'data':{'target_operation_id':pending['operation_id']}})

    def inspect_pending_model(self):
        """Out-of-band read; never cancel/replay or clear the pending model call."""
        pending=self.pending
        if pending is None or pending['action']!='model_complete':raise ValueError('No pending model invocation')
        return self._send({'operation_id':uuid.uuid4().hex,'action':'model_status','run_id':pending['run_id'],
                          'data':{'target_operation_id':pending['operation_id']}})

    def reserve(self,tokens,*,request_id=None):
        return self._rpc('reserve',{'tokens':tokens,'request_id':request_id or uuid.uuid4().hex})['request_id']

    def settle(self,request_id,actual,*,outcome='completed'):
        return self._rpc('settle',{'request_id':request_id,'actual':actual,'outcome':outcome})

    def finish(self,status):return self._rpc('finish',{'status':status})
    def report(self):return self._rpc('report',{})
    def inspect(self,*,after=0,limit=20):return self._rpc('inspect',{'after':after,'limit':limit})

    def claim_task(self):return self._rpc('queue_claim',{})

    def task_status(self,item_id):return self._rpc('queue_status',{'id':item_id})

    def renew_task(self,item_id,fence):return self._rpc('queue_renew',{'id':item_id,'fence':fence})

    def start_task(self,item_id,fence):return self._rpc('queue_start',{'id':item_id,'fence':fence})

    def finish_task(self,item_id,fence,*,status,artifact_sha256):
        return self._rpc('queue_finish',{'id':item_id,'fence':fence,
            'report':{'status':status,'artifact_sha256':artifact_sha256}})
