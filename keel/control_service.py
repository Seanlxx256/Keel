"""Authenticated governance transport for controlled deployments and tests.

Only the service accesses SQLite. This is a bounded stdlib HTTP prototype, not
a hardened internet-facing server or sandbox security boundary. Optional model
execution remains subject to explicit server grants and bounded dispatch.
"""
import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import ssl
import signal
import threading
import time
import uuid

from .core import BudgetExceeded, PolicyDenied
from .governance import ControlStore, Session, GovernanceUnavailable, encoded, reject_nonfinite, validate_config
from .remote_governance import loopback


OBSERVATIONS={'phase_started','tool_outcome','write_intent','write_completed',
              'verification_intent','verification_outcome','model_format_rejected'}


def required(data,keys):
    if not isinstance(data,dict) or set(data)!=set(keys):raise ValueError('Unexpected operation fields')


def identifier(value):
    if not isinstance(value,str) or not value or len(value)>256:raise ValueError('Invalid bounded identifier')
    return value


class ControlService:
    def __init__(self,config,*,clock=time.time):
        if (not isinstance(config,dict) or not {'path','scopes','principals'}<=config.keys()
                or set(config)-{'path','scopes','principals','tenants','model_proxy','read_broker','execution_broker','mcp_broker'}):raise ValueError('Invalid service config fields')
        if not isinstance(config['scopes'],dict) or not config['scopes']:raise ValueError('Expected scopes')
        self.policies={}
        for scope,policy in config['scopes'].items():
            identifier(scope)
            if not isinstance(policy,dict):raise ValueError('Expected scope policy')
            full={**policy,'path':config['path'],'scope':scope}
            validate_config(full)
            if 'endpoint' in full:raise ValueError('Service requires a local database policy')
            self.policies[scope]=full
        self.principals={};self.credentials=[]
        if not isinstance(config['principals'],list) or not config['principals']:raise ValueError('Expected principals')
        for principal in config['principals']:
            if (not isinstance(principal,dict) or not {'id','token_env','scope','task_id','tools'}<=principal.keys()
                    or set(principal)-{'id','tenant_id','token_env','scope','task_id','tools','trusted_usage','models','require_model_proxy','require_read_broker','require_write_broker','require_execution_broker','require_mcp_broker'}):
                raise ValueError('Invalid principal grant')
            if 'tenant_id' in principal:
                from .tenancy import bounded_id
                bounded_id(principal['tenant_id'])
            identity=identifier(principal['id']);identifier(principal['task_id'])
            if identity in self.principals or principal['scope'] not in self.policies:raise ValueError('Duplicate or unknown principal scope')
            if type(principal.get('trusted_usage',False)) is not bool:raise ValueError('trusted_usage must be boolean')
            if type(principal.get('require_model_proxy',False)) is not bool:raise ValueError('require_model_proxy must be boolean')
            if type(principal.get('require_read_broker',False)) is not bool:raise ValueError('require_read_broker must be boolean')
            if type(principal.get('require_write_broker',False)) is not bool:raise ValueError('require_write_broker must be boolean')
            if type(principal.get('require_execution_broker',False)) is not bool:raise ValueError('require_execution_broker must be boolean')
            if type(principal.get('require_mcp_broker',False)) is not bool:raise ValueError('require_mcp_broker must be boolean')
            aliases=principal.get('models',[])
            if not isinstance(aliases,list) or any(not isinstance(alias,str) or not alias for alias in aliases):
                raise ValueError('Expected model alias grants')
            tools=principal['tools']
            if not isinstance(tools,dict) or any(not isinstance(role,str) or not isinstance(names,list)
                    or any(not isinstance(name,str) or not name for name in names) for role,names in tools.items()):
                raise ValueError('Expected role-scoped tool grants')
            token=os.environ.get(principal['token_env'],'')
            if len(token)<32 or token!=token.strip():raise ValueError('Service credential missing or invalid')
            fingerprint=hashlib.sha256(token.encode()).digest()
            if any(hmac.compare_digest(fingerprint,entry[0]) for entry in self.credentials):raise ValueError('Duplicate service credential')
            self.credentials.append((fingerprint,identity))
            self.principals[identity]=dict(principal)
        # Credentials are not written to SQLite or the ready file.
        self.store=ControlStore(config['path'],clock=clock)
        from .task_queue import TaskQueue
        self.queue=TaskQueue(self.store)
        with self.store.transaction() as db:
            for scope,policy in self.policies.items():
                row=db.execute('SELECT policy,max_tokens,max_calls FROM governance_scopes WHERE scope=?',(scope,)).fetchone()
                if row and tuple(row)!=(encoded(sorted(policy.get('denied_tools',[]))),policy['max_tokens'],policy['max_model_calls']):
                    raise PolicyDenied('Existing scope policy changed; create a new explicit scope')
        from .operation_store import SqliteOperationStore
        self.operations=SqliteOperationStore(self.store)
        from .tenancy import TenantRegistry
        self.tenancy=TenantRegistry(self.store)
        from .tenant_quotas import configure as configure_tenant_quotas
        with self.store.transaction():
            self.tenancy.bind(self.principals.values())
            self.tenant_policies=configure_tenant_quotas(self.store,config.get('tenants'),self.principals.values())
        self.model_proxy=None
        if config.get('model_proxy') is not None:
            from .model_proxy import ModelProxy
            self.model_proxy=ModelProxy(self,config['model_proxy'])
        self.read_broker=None
        if config.get('read_broker') is not None:
            from .tool_broker import ReadToolBroker
            self.read_broker=ReadToolBroker(self,config['read_broker'])
        self.write_broker=None
        if self.read_broker is not None:
            from .write_broker import WriteBroker
            self.write_broker=WriteBroker(self)
        self.execution_broker=None
        if config.get('execution_broker') is not None:
            from .execution_broker import ExecutionBroker
            self.execution_broker=ExecutionBroker(self,config['execution_broker'])
        self.mcp_broker=None
        if config.get('mcp_broker') is not None:
            from .mcp_broker import McpBroker
            self.mcp_broker=McpBroker(self,config['mcp_broker'])
        for principal in self.principals.values():
            if any(alias not in (self.model_proxy.models if self.model_proxy else {}) for alias in principal.get('models',[])):
                raise ValueError('Principal grants an unavailable model alias')
            if principal.get('require_model_proxy') and not principal.get('models'):
                raise ValueError('Proxy-only principal requires a configured model grant')
            if principal.get('require_read_broker') and (self.read_broker is None or self.read_broker.capability(principal) is None):
                raise ValueError('Required read broker is unavailable for this principal task')
            if principal.get('require_write_broker') and (self.write_broker is None or self.write_broker.capability(principal) is None):
                raise ValueError('Required write broker is unavailable for this principal task')
            if principal.get('require_execution_broker') and (self.execution_broker is None or self.execution_broker.capability(principal) is None):
                raise ValueError('Required execution broker unavailable for this principal task')
            if principal.get('require_mcp_broker') and (self.mcp_broker is None or not (self.mcp_broker.capability(principal) or {}).get('tools')):
                raise ValueError('Required MCP broker unavailable for this principal task')

    def authenticate(self,header):
        if not isinstance(header,str) or not header.startswith('Bearer '):raise PolicyDenied('Authentication required')
        fingerprint=hashlib.sha256(header[7:].encode()).digest()
        for expected,identity in self.credentials:
            if hmac.compare_digest(fingerprint,expected):return identity
        raise PolicyDenied('Authentication required')

    def close(self,*,timeout=10):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=30:
            raise ValueError('Managed shutdown budget must be positive and at most 30 seconds')
        deadline=time.monotonic()+timeout
        brokers={name:broker for name,broker in [('acceptance',self.execution_broker),('mcp',self.mcp_broker),
                 ('provider',getattr(self,'model_proxy',None))] if broker is not None}
        if not brokers:return {'status':'not_configured','scope':'No acceptance, MCP or provider proxy to stop'}
        results={};stop_errors={}
        # Stop both admission paths before spending the common wait budget.
        for name,broker in brokers.items():
            try:broker.request_stop()
            except Exception as error:stop_errors[name]=type(error).__name__
        for name,broker in brokers.items():
            try:results[name]=broker.shutdown(timeout=max(.01,deadline-time.monotonic()))
            except Exception as error:results[name]={'status':'cleanup_unconfirmed','error_type':type(error).__name__}
        return {'schema_version':2,'status':'stopped' if not stop_errors and all(v['status']=='stopped' for v in results.values()) else 'cleanup_unconfirmed',
                'components':results,'admission_stop_errors':stop_errors,
                'scope':'Managed acceptance/MCP/provider lifecycle only; external effects, descendants and billing not certified cancelled'}

    def _grant_hash(self,principal):
        value={'grant':principal,'policy':self.policies[principal['scope']]}
        if principal.get('tenant_id') in self.tenant_policies:
            value['tenant_policy']=self.tenant_policies[principal['tenant_id']]
        if principal.get('models'):
            value['model_policies']={alias:self.model_proxy.policy_hashes[alias] for alias in principal['models']}
        if self.read_broker is not None and principal['task_id'] in self.read_broker.policy_hashes:
            value['read_policy']=self.read_broker.policy_hashes[principal['task_id']]
        if self.execution_broker is not None and principal['task_id'] in self.execution_broker.policy_hashes:
            value['execution_policy']=self.execution_broker.policy_hashes[principal['task_id']]
        if self.mcp_broker is not None and principal['task_id'] in self.mcp_broker.policy_hashes:
            value['mcp_policy']=self.mcp_broker.policy_hashes[principal['task_id']]
        return hashlib.sha256(encoded(value).encode()).hexdigest()

    def _session(self,db,principal,run_id):
        identifier(run_id)
        policy=self.policies[principal['scope']]
        grant=self.store.runs.authorize_remote(run_id=run_id,principal=principal['id'],
            task_id=principal['task_id'],scope=principal['scope'],grant_hash=self._grant_hash(principal),
            lease_seconds=policy.get('lease_seconds',3600))
        return Session(self.store,policy,grant.run_id,grant.owner)

    def operate(self,principal_id,request):
        from .transaction_domain import require_shared_domain
        self.store.require_persistence()
        require_shared_domain(self.store,operations=self.operations,queue=self.queue)
        if isinstance(request,dict) and request.get('action')=='model_status':
            if self.model_proxy is None:raise PolicyDenied('Model proxy unavailable')
            required(request,{'operation_id','action','run_id','data'});required(request['data'],{'target_operation_id'})
            return {'ok':True,'result':self.model_proxy.inspect(principal_id,request['run_id'],request['data']['target_operation_id'])}
        if isinstance(request,dict) and request.get('action') in {'mcp_call','mcp_page','mcp_cancel','mcp_preflight'}:
            if self.mcp_broker is None:raise PolicyDenied('MCP broker unavailable')
            return self.mcp_broker.operate(principal_id,request)
        if isinstance(request,dict) and request.get('action') in {'verify_start','verify_status','verify_page'}:
            if self.execution_broker is None:raise PolicyDenied('Execution broker unavailable')
            return self.execution_broker.operate(principal_id,request)
        if isinstance(request,dict) and request.get('action') in {'tool_replace','tool_write_status'}:
            if self.write_broker is None:raise PolicyDenied('Write broker is not configured')
            if request['action']=='tool_replace':return self.write_broker.execute(principal_id,request)
            required(request,{'operation_id','action','run_id','data'});required(request['data'],{'write_operation_id'})
            return {'ok':True,'result':self.write_broker.inspect(principal_id,request['run_id'],request['data']['write_operation_id'])}
        if isinstance(request,dict) and request.get('action')=='tool_read':
            if self.read_broker is None:raise PolicyDenied('Read broker is not configured')
            return self.read_broker.execute(principal_id,request)
        if isinstance(request,dict) and request.get('action')=='model_complete':
            if self.model_proxy is None:raise PolicyDenied('Model proxy is not configured')
            try:return self.model_proxy.execute(principal_id,request)
            except BudgetExceeded as error:
                return {'ok':False,'error_type':'BudgetExceeded','message':str(error)}
        principal=self.principals[principal_id]
        if not isinstance(request,dict) or set(request)-{'operation_id','action','data','run_id'} or not {'operation_id','action','data'}<=request.keys():
            raise ValueError('Invalid operation envelope')
        operation_id=identifier(request['operation_id']);action=request['action'];data=request['data']
        if not isinstance(action,str) or not isinstance(data,dict):raise ValueError('Invalid action or data')
        if (action=='begin') == ('run_id' in request):raise ValueError('Only non-begin operations require run_id')
        fingerprint=hashlib.sha256(encoded(request).encode()).hexdigest()
        def prepare(db):
            return self._session(db,principal,request.get('run_id')) if action!='begin' else None
        def replay(db,session,response):
            if action in {'reserve','tool_started','queue_claim','queue_start','queue_renew'}:
                session._active(db)
                if action in {'queue_claim','queue_start'} and response.get('ok'):
                    # Historical receipt cannot authorize another dispatch.
                    response['result']['dispatch_allowed']=False
                    response['result']['historical_response']=True
            return response
        def apply(db,session):
            try:
                result=self._execute(db,principal,session,action,data)
                response={'ok':True,'result':result}
            except (PolicyDenied,BudgetExceeded,ValueError,KeyError) as error:
                if isinstance(error,GovernanceUnavailable):raise
                response={'ok':False,'error_type':type(error).__name__,'message':str(error)}
            return response
        return self.operations.execute(principal=principal_id,operation_id=operation_id,
            request_hash=fingerprint,prepare=prepare,apply=apply,replay=replay,
            record=action not in {'report','inspect','queue_status'})

    def _execute(self,db,principal,session,action,data):
        if action=='queue_status':
            required(data,{'id'})
            return self.queue.status(principal['id'],principal['task_id'],data['id'])
        if action in {'queue_claim','queue_start','queue_finish','queue_renew'}:
            session._active(db)
            deadline=self.store.runs.get_bound(session._run_grant()).deadline
            if action=='queue_claim':
                required(data,set())
                return self.queue.claim(principal['id'],principal['task_id'],session.run_id,deadline)
            if action=='queue_renew':
                required(data,{'id','fence'})
                return self.queue.renew(principal['id'],principal['task_id'],session.run_id,
                                        data['id'],data['fence'],deadline)
            required(data,{'id','fence'} if action=='queue_start' else {'id','fence','report'})
            return self.queue.transition(principal['id'],principal['task_id'],session.run_id,
                data['id'],data['fence'],'start' if action=='queue_start' else 'finish',data.get('report'))
        if action=='begin':
            required(data,{'task_id','identity','wallclock_seconds'})
            if data['task_id']!=principal['task_id']:raise PolicyDenied('Task not granted to principal')
            identity=identifier(data['identity']);wallclock=data['wallclock_seconds']
            policy=self.policies[principal['scope']]
            lease=policy.get('lease_seconds',3600)
            if type(wallclock) not in (int,float) or not math.isfinite(wallclock) or not 0<wallclock<lease:
                raise ValueError('Runtime wall-clock budget must be positive and below server lease')
            run_id=uuid.uuid4().hex
            session=self.store.begin(policy,run_id,identity)
            self.store.runs.bind_remote(session._run_grant(),principal['id'],principal['task_id'],self._grant_hash(principal))
            result={'run_id':run_id,'scope':principal['scope'],'lease_seconds':lease}
            if 'tenant_id' in principal:result['tenant_id']=principal['tenant_id']
            if self.read_broker is not None:
                capability=self.read_broker.capability(principal)
                if capability is not None:result['read_broker']=capability
            if self.write_broker is not None:
                capability=self.write_broker.capability(principal)
                if capability is not None:result['write_broker']=capability
            if self.execution_broker is not None:
                capability=self.execution_broker.capability(principal)
                if capability is not None:result['execution_broker']=capability
            if self.mcp_broker is not None:
                capability=self.mcp_broker.capability(principal)
                if capability is not None:result['mcp_broker']=capability
            return result
        if action=='reserve':
            if principal.get('require_model_proxy'):raise PolicyDenied('This principal must execute models through the controller proxy')
            required(data,{'tokens','request_id'})
            return {'request_id':session.reserve(data['tokens'],request_id=identifier(data['request_id']))}
        if action=='tool_started':
            required(data,{'role','tool','action_id'})
            for name in data.values():identifier(name)
            if principal.get('require_mcp_broker') and data['tool'].startswith('mcp__'):
                raise PolicyDenied('MCP calls must execute through the controller broker')
            if principal.get('require_write_broker') and data['tool']=='replace':
                raise PolicyDenied('Replacements must execute through the controller broker')
            if principal.get('require_read_broker'):
                from .tool_broker import READ_TOOLS
                if data['tool'] in READ_TOOLS:raise PolicyDenied('Read tools must execute through the controller broker')
            if data['tool'] not in principal['tools'].get(data['role'],[]):
                session.event('authorization_denied',{'principal':principal['id'],'role':data['role'],'tool':data['tool']},action_id=data['action_id'])
                raise PolicyDenied('Tool not granted to this principal and role')
            session.tool_started(data['role'],data['tool'],data['action_id'])
            return {'authorized':True}
        if action=='event':
            required(data,{'kind','payload','action_id'})
            if data['kind'] not in OBSERVATIONS:raise PolicyDenied('Worker cannot publish authoritative control events')
            if principal.get('require_execution_broker') and data['kind'] in {'verification_intent','verification_outcome'}:
                raise PolicyDenied('This principal must request controller-executed acceptance')
            identifier(data['action_id'])
            session.event('worker_observation',{'principal':principal['id'],'kind':data['kind'],'reported_payload':data['payload'],
                'authority':'worker report, not independent execution proof'},action_id=data['action_id'])
            return {'recorded':True}
        if action=='settle':
            if principal.get('require_model_proxy'):raise PolicyDenied('Proxy-only usage is settled by the controller provider adapter')
            required(data,{'request_id','actual','outcome'})
            identifier(data['request_id']);identifier(data['outcome'])
            actual=data['actual']
            if actual is not None and (type(actual) is not int or actual<0):raise ValueError('Invalid usage')
            if principal.get('trusted_usage',False):
                session.settle(data['request_id'],actual,outcome=data['outcome'])
                return {'usage_authority':'trusted worker accounting'}
            # An untrusted worker cannot release quota by claiming zero usage.
            session.settle(data['request_id'],None,outcome='unverified_worker_usage')
            self.store._event(db,session.run_id,data['request_id'],'worker_usage_report',
                {'reported_tokens':actual,'quota_released':False})
            return {'usage_authority':'unverified','quota_released':False}
        if action=='finish':
            required(data,{'status'})
            session.event('worker_observation',{'principal':principal['id'],'kind':'finish',
                'reported_status':data['status'],'authority':'not independent acceptance'})
            return self._report(session,session.finish(data['status']))
        if action=='report':
            required(data,set())
            return self._report(session,session.report())
        if action=='inspect':
            required(data,{'after','limit'})
            if type(data['limit']) is not int or not 1<=data['limit']<=20:raise ValueError('Inspection page must be 1..20 events')
            result=self.store.inspect(scope=principal['scope'],run_id=session.run_id,after=data['after'],limit=data['limit'])
            for event in result['events']:
                if event['action_id']==session.owner:
                    event['action_id']='control-lifecycle-'+str(event['seq'])
            # Never silently truncate the contents of an individual evidence
            # record. Shorten the page and return its actual continuation.
            while len(encoded(result).encode())>240000 and len(result['events'])>1:result['events'].pop()
            result['next_after']=result['events'][-1]['seq'] if result['events'] else data['after']
            return result
        raise ValueError('Unsupported control operation')

    @staticmethod
    def _report(session,result):
        result=dict(result);result.pop('path',None)
        result['transport']='authenticated_control_service'
        result['verdict_source']='worker report, not independently verified'
        result['scope_note']='Server-owned quota and policy; unknown usage retained. Worker observations are not trusted execution proofs.'
        return result


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    block_on_close=False

    def __init__(self,address,service,max_workers):
        self.service=service
        self.slots=threading.BoundedSemaphore(max_workers)
        super().__init__(address,Handler)

    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally:self.shutdown_request(request)
            return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise

    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(3)
        if isinstance(self.request,ssl.SSLSocket):self.request.do_handshake()
        super().setup()

    def log_message(self,*args):pass  # Never log headers or bearer credentials.

    def reply(self,status,value):
        raw=encoded(value).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)));self.send_header('Connection','close');self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionError,OSError):pass

    def do_POST(self):
        try:
            if self.path!='/v1/operation':return self.reply(404,{'ok':False,'message':'Not found'})
            headers=self.headers.get_all('Authorization',[])
            if len(headers)!=1:raise PolicyDenied('Authentication required')
            principal=self.server.service.authenticate(headers[0])
            lengths=self.headers.get_all('Content-Length',[])
            if self.headers.get('Transfer-Encoding') or len(lengths)!=1:raise ValueError('Expected one Content-Length, no chunked transfer')
            length=int(lengths[0])
            if not 0<length<=131072:return self.reply(413,{'ok':False,'message':'Request too large'})
            raw=self.rfile.read(length)
            if len(raw)!=length:raise ValueError('Incomplete request')
            request=json.loads(raw.decode('utf-8'),parse_constant=reject_nonfinite)
            response=self.server.service.operate(principal,request)
            return self.reply(200,response)
        except GovernanceUnavailable:
            return self.reply(503,{'ok':False,'message':'Required control storage unavailable'})
        except PolicyDenied:
            return self.reply(403,{'ok':False,'error_type':'PolicyDenied','message':'Request not authorized'})
        except (ValueError,UnicodeError,KeyError,TypeError):
            return self.reply(400,{'ok':False,'error_type':'ValueError','message':'Invalid control request'})
        except (TimeoutError,ConnectionError,OSError):
            return self.reply(503,{'ok':False,'message':'Control request interrupted'})


def make_server(service,*,host='127.0.0.1',port=0,max_workers=16,tls_context=None):
    if not loopback(host) and tls_context is None:raise ValueError('Non-loopback listener requires TLS')
    if type(max_workers) is not int or not 1<=max_workers<=128:raise ValueError('Expected bounded worker count')
    server=BoundedHTTPServer((host,port),service,max_workers)
    if tls_context is not None:
        # Defer handshakes to bounded request workers, not the accept loop.
        server.socket=tls_context.wrap_socket(server.socket,server_side=True,do_handshake_on_connect=False)
    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--max-seconds',type=float,default=300)
    parser.add_argument('--shutdown-seconds',type=float,default=10)
    parser.add_argument('--ready-file',type=Path,required=True)
    parser.add_argument('--cert',type=Path);parser.add_argument('--key',type=Path)
    args=parser.parse_args()
    if not math.isfinite(args.max_seconds) or args.max_seconds<=0:parser.error('max-seconds must be finite and positive')
    if not math.isfinite(args.shutdown_seconds) or not 0<args.shutdown_seconds<=30:parser.error('shutdown-seconds must be positive and at most 30')
    if bool(args.cert)!=bool(args.key):parser.error('cert and key must be provided together')
    if args.ready_file.exists():raise ValueError('Ready receipt exists; preserve previous service evidence')
    context=None
    if args.cert:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.cert,args.key)
    service=ControlService(json.loads(args.config.read_text(encoding='utf-8')))
    with make_server(service,host=args.host,port=args.port,tls_context=context) as server:
        from compass.progress import atomic_json
        args.ready_file.parent.mkdir(parents=True,exist_ok=True)
        endpoint=('https' if context else 'http')+'://'+args.host+':'+str(server.server_address[1])
        atomic_json(args.ready_file,{'endpoint':endpoint,'pid':os.getpid(),'scope':'Bounded control-service prototype'})
        print('[Control service] listening; maximum '+str(args.max_seconds)+' seconds',flush=True)
        server.timeout=.2;deadline=time.monotonic()+args.max_seconds;next_progress=time.monotonic()+10
        stopped=threading.Event();handlers={}
        try:
            for number in (signal.SIGINT,signal.SIGTERM):
                handlers[number]=signal.signal(number,lambda *_:stopped.set())
            while time.monotonic()<deadline and not stopped.is_set():
                server.handle_request()
                if time.monotonic()>=next_progress:
                    service.store.reconcile_expired()
                    print('[Control service] alive; remaining='+str(round(deadline-time.monotonic(),1))+'s',flush=True)
                    next_progress=time.monotonic()+10
        finally:
            try:
                print('[Control service] managed shutdown; <='+str(args.shutdown_seconds)+'s plus storage operations',flush=True)
                try:receipt=service.close(timeout=args.shutdown_seconds)
                except Exception as error:receipt={'status':'cleanup_unconfirmed','error_type':type(error).__name__}
                atomic_json(args.ready_file.with_name(args.ready_file.name+'.execution-shutdown.json'),receipt)
                if receipt.get('status')=='cleanup_unconfirmed':raise SystemExit(1)
            finally:
                for number,previous in handlers.items():signal.signal(number,previous)


if __name__=='__main__':main()
