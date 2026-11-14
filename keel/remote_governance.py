"""Bounded client for the separate governance service; no automatic RPC retry."""
import ipaddress
import json
import math
import os
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

from .core import BudgetExceeded, PolicyDenied
from .governance import GovernanceUnavailable, encoded


def loopback(host):
    if host == 'localhost':return True
    try:return ipaddress.ip_address(host).is_loopback
    except ValueError:return False


def validate_remote_config(config):
    required={'endpoint','token_env','task_id'}
    if not isinstance(config,dict) or not required <= config.keys() or set(config)-required-{'timeout_seconds'}:
        raise ValueError('Remote governance accepts endpoint, token_env, task_id and timeout_seconds only')
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
        token=os.environ.get(config['token_env'],'')
        if not token or token!=token.strip() or len(token)<32:
            raise PolicyDenied('Remote governance credential missing or invalid')
        self._token=token

    @classmethod
    def begin(cls,config,identity,wallclock,*,budget=None):
        session=cls(config)
        session.budget=budget
        try:result=session._rpc('begin',{'task_id':config['task_id'],'identity':identity,'wallclock_seconds':wallclock})
        except GovernanceUnavailable as error:
            error.governance_session=session
            raise
        session.run_id=result['run_id']
        session.config={'scope':result['scope'],'lease_seconds':result['lease_seconds']}
        return session

    def _send(self,operation):
        raw=encoded(operation).encode('utf-8')
        if len(raw)>131072:raise ValueError('Control request too large; send artifact references')
        request=urllib.request.Request(self.location+'/v1/operation',data=raw,
            headers={'Content-Type':'application/json','Authorization':'Bearer '+self._token},method='POST')
        try:
            # Do not leak credentials through inherited proxies or redirects.
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
            timeout=self.client_config.get('timeout_seconds',3)
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
            error={'BudgetExceeded':BudgetExceeded,'PolicyDenied':PolicyDenied,'ValueError':ValueError}.get(kind,GovernanceUnavailable)
            raise error(value.get('message','Control operation rejected'))
        return value['result']

    def _rpc(self,action,data):
        with self._lock:
            return self._rpc_locked(action,data)

    def _rpc_locked(self,action,data):
        if self.budget is not None and action in {'begin','reserve','tool_started'}:self.budget.check()
        if self.pending is not None:
            raise GovernanceUnavailable('Unconfirmed control operation; reconcile the exact operation before new work')
        operation={'operation_id':uuid.uuid4().hex,'action':action,'data':data}
        if self.run_id is not None:operation['run_id']=self.run_id
        self.pending=operation
        try:
            result=self._send(operation)
        except GovernanceUnavailable:
            raise
        except BaseException:
            self.pending=None
            raise
        self.pending=None
        return result

    def reconcile_pending(self):
        """Repeat the exact RPC ID, not the model/tool action it authorized."""
        with self._lock:
            return self._reconcile_locked()

    def _reconcile_locked(self):
        if self.pending is None:raise ValueError('No unconfirmed operation')
        action=self.pending['action']
        try:result=self._send(self.pending)
        except GovernanceUnavailable:raise
        except BaseException:
            self.pending=None
            raise
        self.pending=None
        if action=='begin':
            self.run_id=result['run_id']
            self.config={'scope':result['scope'],'lease_seconds':result['lease_seconds']}
        return result

    def event(self,kind,payload,*,action_id=None):
        return self._rpc('event',{'kind':kind,'payload':payload,'action_id':action_id or uuid.uuid4().hex})

    def tool_started(self,role,tool,action_id):
        return self._rpc('tool_started',{'role':role,'tool':tool,'action_id':action_id})

    def reserve(self,tokens,*,request_id=None):
        return self._rpc('reserve',{'tokens':tokens,'request_id':request_id or uuid.uuid4().hex})['request_id']

    def settle(self,request_id,actual,*,outcome='completed'):
        return self._rpc('settle',{'request_id':request_id,'actual':actual,'outcome':outcome})

    def finish(self,status):return self._rpc('finish',{'status':status})
    def report(self):return self._rpc('report',{})
    def inspect(self,*,after=0,limit=20):return self._rpc('inspect',{'after':after,'limit':limit})
