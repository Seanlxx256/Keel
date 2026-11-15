"""Server-configured navigation MCP execution, with source-bound provenance."""
import base64
from contextlib import ExitStack
import hashlib
import json
import math
import threading
import time

from compass.progress import atomic_json
from .core import Budget, Ledger, Limits, PolicyDenied, Trace, digest
from .execution_broker import VerificationWorkspace
from .governance import GovernanceUnavailable, encoded
from .mcp_client import McpTools, McpToolError, McpTransportUnavailable, validate_servers
from .async_process_lifecycle import RequestControl


class McpBroker:
    def __init__(self,service,config):
        if not isinstance(config,dict) or set(config)!={'tasks'} or not isinstance(config['tasks'],dict):
            raise ValueError('MCP broker requires fixed task mappings')
        if service.read_broker is None:raise ValueError('MCP broker requires controller repository bindings')
        self.service=service;self.tasks={};self.policy_hashes={}
        self.stopping=threading.Event();self.lifecycle_lock=threading.Lock()
        self.active={};self.recent={};self.receipt_failures=0
        for task,spec in config['tasks'].items():
            if task not in service.read_broker.repositories or not isinstance(spec,dict) or set(spec)!={'servers','path_arguments'}:
                raise ValueError('MCP task requires servers and explicit path_arguments')
            validate_servers(spec['servers'])
            tools=McpTools(spec['servers'],None);policies={}
            for server in spec['servers'].values():
                if server.get('timeout',30)>20:raise ValueError('Controller navigation MCP timeout must be at most 20 seconds')
            for role in ('scout','planner','implementer'):
                for alias in tools.catalog(role):policies[alias]=tools.policy(alias)
            if not isinstance(spec['path_arguments'],dict) or set(spec['path_arguments'])!=set(policies):
                raise ValueError('Every MCP alias must explicitly declare its file argument names, including []')
            for alias,policy in policies.items():
                schema=policy.get('input_schema')
                if policy.get('read_only') is not True or not isinstance(schema,dict) or schema.get('additionalProperties') is not False:
                    raise ValueError('Navigation MCP requires explicit read_only and closed input_schema')
                fields=spec['path_arguments'][alias]
                if not isinstance(fields,list) or any(not isinstance(name,str) or name not in schema.get('properties',{}) for name in fields):
                    raise ValueError('Invalid declared MCP file fields')
            self.tasks[task]={'servers':spec['servers'],'path_arguments':spec['path_arguments'],'policies':policies}
            self.policy_hashes[task]=digest(spec)
        with service.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS broker_mcp_preflights (
                principal TEXT NOT NULL, run_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                status TEXT NOT NULL, response TEXT, PRIMARY KEY(principal,run_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS broker_mcp_requests (
                principal TEXT NOT NULL, operation_id TEXT NOT NULL, run_id TEXT NOT NULL,
                request_hash TEXT NOT NULL, status TEXT NOT NULL, response TEXT,
                PRIMARY KEY(principal,operation_id))''')

    def capability(self,principal):
        spec=self.tasks.get(principal['task_id'])
        if spec is None:return None
        policies={}
        for alias,policy in spec['policies'].items():
            roles=[role for role in policy['roles'] if alias in principal['tools'].get(role,[])]
            if roles:policies[alias]={**policy,'roles':roles}
        return {'tools':policies,'policy_sha256':self.policy_hashes[principal['task_id']],
                'required':principal.get('require_mcp_broker',False)}

    def _folder(self,run_id,operation):
        return self.service.read_broker.evidence/run_id/('mcp-'+hashlib.sha256(operation.encode()).hexdigest())

    def _preflight(self,principal_id,principal,request):
        from .mcp_preflight import check_host, validate_policy
        data=request['data']
        if not isinstance(data,dict) or set(data)!={'timeout'}:raise ValueError('Invalid preflight fields')
        validate_policy({'timeout_seconds':data['timeout']})
        if not self.capability(principal)['tools']:raise PolicyDenied('No MCP tools granted')
        fingerprint=digest([data,self.policy_hashes[principal['task_id']]])
        with self.service.store.transaction() as db:
            session=self.service._session(db,principal,request['run_id']);session._active(db)
            row=db.execute('SELECT * FROM broker_mcp_preflights WHERE principal=? AND run_id=?',
                           (principal_id,session.run_id)).fetchone()
            if row:
                if row['request_hash']!=fingerprint:raise PolicyDenied('Preflight configuration changed within run')
                if row['status']!='complete':raise GovernanceUnavailable('Preflight unfinished; no repeat')
                return json.loads(row['response'])
            if self.stopping.is_set():raise GovernanceUnavailable('MCP broker stopping; no new preflight')
            db.execute('INSERT INTO broker_mcp_preflights VALUES(?,?,?,?,NULL)',
                       (principal_id,session.run_id,fingerprint,'inflight'))
        report=check_host(self.tasks[principal['task_id']]['servers'],timeout=data['timeout'])
        report.update({'authority':'controller host capability probe','run_id':session.run_id,
                       'policy_sha256':self.policy_hashes[principal['task_id']]})
        folder=self._folder(session.run_id,'preflight');folder.mkdir(parents=True,exist_ok=True)
        atomic_json(folder/'result.json',report)
        response={'ok':True,'result':report}
        with self.service.store.transaction() as db:
            self.service.store._event(db,session.run_id,request['operation_id'],'broker_mcp_preflight',report)
            db.execute("UPDATE broker_mcp_preflights SET status='complete',response=? WHERE principal=? AND run_id=?",
                       (encoded(response),principal_id,session.run_id))
        return response

    def operate(self,principal_id,request):
        if not isinstance(request,dict) or set(request)!={'operation_id','action','run_id','data'}:
            raise ValueError('Invalid MCP broker envelope')
        operation=request['operation_id']
        if not isinstance(operation,str) or not 0<len(operation)<=256:raise ValueError('Invalid MCP operation ID')
        principal=self.service.principals[principal_id]
        if not self.capability(principal):raise PolicyDenied('MCP broker unavailable to principal')
        if request['action']=='mcp_page':return self._page(principal,request)
        if request['action']=='mcp_cancel':return self._cancel(principal,request)
        if request['action']=='mcp_preflight':return self._preflight(principal_id,principal,request)
        if request['action']!='mcp_call':raise ValueError('Invalid MCP broker action')
        if self.stopping.is_set():raise GovernanceUnavailable('MCP broker stopping; no new invocation')
        data=request['data']
        if not isinstance(data,dict) or set(data)!={'role','alias','arguments','source_sha256','timeout'}:
            raise ValueError('Invalid MCP invocation fields')
        capability=self.capability(principal);policy=capability['tools'].get(data['alias']) if isinstance(data['alias'],str) else None
        if policy is None or data['role'] not in policy['roles']:raise PolicyDenied('MCP alias/role not granted')
        try:from jsonschema import Draft202012Validator
        except ImportError:raise ValueError('Controller MCP schema validation requires the mcp optional dependencies') from None
        if not isinstance(data['arguments'],dict) or not Draft202012Validator(policy['input_schema']).is_valid(data['arguments']):
            raise ValueError('MCP arguments do not match operator schema; no tool dispatch')
        spec=self.tasks[principal['task_id']];read=self.service.read_broker
        approved=read.repositories[principal['task_id']]
        for name in spec['path_arguments'][data['alias']]:
            if name in data['arguments'] and data['arguments'][name] not in approved['files']:
                raise PolicyDenied('MCP file argument outside explicit read catalog')
        timeout=data['timeout']
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=20:
            raise ValueError('MCP broker timeout must be positive and at most 20 seconds')
        if not isinstance(data['source_sha256'],str) or len(data['source_sha256'])!=64:raise ValueError('Invalid source fingerprint')
        fingerprint=digest([request,self.policy_hashes[principal['task_id']]])
        if not read.slot.acquire(blocking=False):raise GovernanceUnavailable('Controller source broker busy')
        control=RequestControl();key=(principal_id,operation)
        with self.lifecycle_lock:
            if self.stopping.is_set():
                read.slot.release();raise GovernanceUnavailable('MCP broker stopped before invocation')
            self.active[key]=control
        ledger=None;attempted=False;returned=False;new_intent=False;prepared=False;publishing=False
        try:
            with self.service.store.transaction() as db:
                session=self.service._session(db,principal,request['run_id'])
                row=db.execute('SELECT * FROM broker_mcp_requests WHERE principal=? AND operation_id=?',(principal_id,operation)).fetchone()
                if row:
                    if row['request_hash']!=fingerprint:raise PolicyDenied('MCP operation ID changed input')
                    if row['status']!='complete':raise GovernanceUnavailable('MCP outcome unknown; no implicit repeat')
                    return json.loads(row['response'])
                session.tool_started(data['role'],data['alias'],operation)
                db.execute('INSERT INTO broker_mcp_requests VALUES(?,?,?,?,?,NULL)',
                           (principal_id,operation,session.run_id,fingerprint,'inflight'))
            new_intent=True
            folder=self._folder(session.run_id,operation);folder.mkdir(parents=True,exist_ok=False)
            control.on_update=lambda value:atomic_json(folder/'lifecycle.json',
                {'principal':principal_id,'run_id':session.run_id,'operation_id':operation,**value})
            control.checkpoint()
            ledger=Ledger(folder/'ledger.sqlite')
            ws=VerificationWorkspace(approved['root'],Budget(Limits(max_wallclock=timeout,max_tool_calls=1)),
                                     ledger,Trace(folder/'trace.jsonl'))
            def before_call():
                nonlocal attempted
                if self.stopping.is_set() or control.requested.is_set() or control.storage_failed:
                    raise GovernanceUnavailable('MCP cancelled or lifecycle storage unavailable before dispatch')
                with self.service.store.transaction() as db:
                    session._active(db)
                    self.service.store._event(db,session.run_id,operation,'broker_mcp_dispatch',{'alias':data['alias'],'role':data['role']})
                attempted=True
            def after_result():
                nonlocal returned
                returned=True
            with ExitStack() as locks:
                for name in sorted(approved['writable_files']):
                    locks.enter_context(self.service.write_broker._path_lock(ws.path(name,write=True)))
                before=ws.snapshot()
                if digest(before)!=data['source_sha256']:raise PolicyDenied('MCP source differs from worker')
                tools=McpTools(spec['servers'],ws,before_tool_call=before_call,after_tool_result=after_result,request_control=control)
                prepared=True
                try:
                    value=tools.call(data['role'],data['alias'],data['arguments'])
                    if not attempted or not returned:raise GovernanceUnavailable('MCP adapter returned without dispatch/result receipt')
                    lifecycle=control.report()
                    if not lifecycle['request_finished'] or not lifecycle['direct_children_exited'] or control.storage_failed:
                        raise GovernanceUnavailable('MCP lifecycle cleanup/storage unconfirmed')
                    if ws.snapshot()!=before:raise GovernanceUnavailable('Navigation MCP changed source; do not repeat')
                    observation={'authority':'controller MCP invocation with untrusted server output',
                        'operation_id':operation,'source_sha256':digest(before),'alias':data['alias'],'output':value}
                    publishing=True
                    atomic_json(folder/'result.json',observation)
                    raw=(folder/'result.json').read_bytes()
                    response={'ok':True,'result':{'operation_id':operation,'artifact_sha256':hashlib.sha256(raw).hexdigest(),
                        'artifact_bytes':len(raw),'source_sha256':digest(before)}}
                except Exception as error:
                    lifecycle=control.report()
                    if (publishing or (attempted and not returned) or control.storage_failed
                            or not lifecycle['request_finished'] or not lifecycle['direct_children_exited'] or ws.snapshot()!=before):
                        raise GovernanceUnavailable('MCP effect/result uncertain; inspect original invocation') from error
                    kind=('McpTransportUnavailable' if isinstance(error,McpTransportUnavailable)
                          else 'McpToolError' if isinstance(error,McpToolError) else 'ValueError')
                    response={'ok':False,'error_type':kind,'message':'Controller MCP failed: '+type(error).__name__}
                    if isinstance(error,McpToolError) and isinstance(getattr(error,'failure',None),dict):
                        response['failure']={key:value for key,value in error.failure.items() if key!='artifact'}
                        response['failure']['controller_receipt_name']=error.failure.get('artifact','').replace('\\','/').rsplit('/',1)[-1]
            with self.service.store.transaction() as db:
                self.service.store._event(db,session.run_id,operation,'broker_mcp_outcome',{'completed':response['ok'],'alias':data['alias']})
                db.execute("UPDATE broker_mcp_requests SET status='complete',response=? WHERE principal=? AND operation_id=?",
                           (encoded(response),principal_id,operation))
            return response
        except Exception as error:
            if new_intent and not prepared:
                response={'ok':False,'error_type':'PolicyDenied' if isinstance(error,PolicyDenied) else 'ValueError',
                          'message':'MCP preparation failed before invocation: '+type(error).__name__}
                with self.service.store.transaction() as db:
                    self.service.store._event(db,session.run_id,operation,'broker_mcp_preparation_rejected',{'error_type':type(error).__name__})
                    db.execute("UPDATE broker_mcp_requests SET status='complete',response=? WHERE principal=? AND operation_id=?",
                               (encoded(response),principal_id,operation))
                return response
            raise
        finally:
            try:
                if ledger is not None:ledger.close()
            finally:
                try:
                    if control.loop is None and not control.finished:control.finish()
                    if new_intent:control.checkpoint()
                finally:
                    receipt=control.report()
                    with self.lifecycle_lock:
                        self.active.pop(key,None)
                        if new_intent:
                            self.recent[key]={'principal':principal_id,'operation_id':operation,**receipt}
                            if len(self.recent)>32:self.recent.pop(next(iter(self.recent)))
                            if receipt['storage_failed'] or not receipt['direct_children_exited']:self.receipt_failures+=1
                    read.slot.release()

    def _cancel(self,principal,request):
        data=request['data']
        if not isinstance(data,dict) or set(data)!={'target_operation_id'} or not isinstance(data['target_operation_id'],str):
            raise ValueError('Cancellation requires a target operation ID')
        with self.service.store.transaction() as db:
            self.service._session(db,principal,request['run_id'])
            row=db.execute('SELECT * FROM broker_mcp_requests WHERE principal=? AND operation_id=? AND run_id=?',
                (principal['id'],data['target_operation_id'],request['run_id'])).fetchone()
            if row is None:raise PolicyDenied('MCP invocation unavailable to this principal/run')
        with self.lifecycle_lock:control=self.active.get((principal['id'],data['target_operation_id']))
        if control is not None:control.cancel()
        with self.service.store.transaction() as db:
            self.service.store._event(db,request['run_id'],data['target_operation_id'],'broker_mcp_cancel_requested',
                {'active_owned_request_found':control is not None,'result_unknown_preserved':row['status']!='complete'})
        return {'ok':True,'result':{'status':'cancel_requested' if control is not None else 'not_active_in_this_instance',
                                  'cancellation_confirmed':False,'replay_authorized':False}}

    def request_stop(self):
        with self.lifecycle_lock:
            self.stopping.set();controls=list(self.active.values())
        for control in controls:control.cancel()

    def shutdown(self,*,timeout=10):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=30:
            raise ValueError('MCP shutdown budget must be positive and at most 30 seconds')
        deadline=time.monotonic()+timeout;self.request_stop()
        while time.monotonic()<deadline:
            with self.lifecycle_lock:
                if not self.active:break
            time.sleep(min(.02,max(.001,deadline-time.monotonic())))
        with self.lifecycle_lock:
            active=[{'principal':key[0],'operation_id':key[1],**value.report()} for key,value in self.active.items()]
            recent=list(self.recent.values());failures=self.receipt_failures
        return {'status':'stopped' if not active and failures==0 else 'cleanup_unconfirmed','active':active,
                'recent_lifecycle_receipts':recent,'unconfirmed_cleanup_or_storage_count':failures,
                'scope':'Current-instance MCP requests/direct SDK children only; unknown external effects remain unknown'}

    def _page(self,principal,request):
        data=request['data']
        if not isinstance(data,dict) or set(data)!={'target_operation_id','offset'} or type(data['offset']) is not int or data['offset']<0:
            raise ValueError('Invalid MCP artifact page')
        if not isinstance(data['target_operation_id'],str):raise ValueError('Invalid MCP target operation')
        with self.service.store.transaction() as db:
            self.service._session(db,principal,request['run_id'])
            row=db.execute('SELECT * FROM broker_mcp_requests WHERE principal=? AND operation_id=? AND run_id=?',
                           (principal['id'],data['target_operation_id'],request['run_id'])).fetchone()
            if not row or row['status']!='complete' or not json.loads(row['response']).get('ok'):raise PolicyDenied('MCP artifact unavailable')
        path=self._folder(request['run_id'],data['target_operation_id'])/'result.json'
        with path.open('rb') as stream:stream.seek(data['offset']);raw=stream.read(65536)
        if not raw:raise ValueError('MCP artifact offset outside result')
        return {'ok':True,'result':{'data_base64':base64.b64encode(raw).decode(),
            'next_offset':data['offset']+len(raw) if data['offset']+len(raw)<path.stat().st_size else None}}


class RoutedMcpTools:
    def __init__(self,local,workspace):
        self.local=local;self.ws=workspace;self.remote=workspace.governance
        self.capability=self.remote.config['mcp_broker'];self.tools=self.capability['tools']
        if self.capability.get('required') and local.servers:raise ValueError('Proxy-only MCP principal must remove worker-local MCP servers')
        for role in ('scout','planner','implementer'):
            if set(local.catalog(role))&set(self.tools):raise ValueError('Local and controller MCP aliases overlap')

    def catalog(self,role):
        return {**self.local.catalog(role),**{alias:policy['description'] for alias,policy in self.tools.items() if role in policy['roles']}}

    def policy(self,alias):return self.tools[alias] if alias in self.tools else self.local.policy(alias)

    def transport(self,alias):return 'control-proxy' if alias in self.tools else self.local.transport(alias)

    def call(self,role,alias,arguments):
        if alias not in self.tools:return self.local.call(role,alias,arguments)
        if role not in self.tools[alias]['roles']:raise PolicyDenied('Controller MCP role denied')
        self.ws.budget.charge_tool();before=digest(self.ws.snapshot())
        value=self.remote.call_mcp(role,alias,arguments,before,min(20,self.ws.budget.remaining))
        if (value.get('source_sha256')!=before or digest(self.ws.snapshot())!=before
                or value.get('authority')!='controller MCP invocation with untrusted server output'):
            raise PolicyDenied('MCP provenance/source changed; reject observation')
        return value
