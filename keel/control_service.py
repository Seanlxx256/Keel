"""Authenticated governance transport for controlled deployments and tests.

Only the service accesses SQLite. This is a bounded stdlib HTTP prototype, not
a hardened internet-facing server, model proxy, or sandbox security boundary.
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
        required(config,{'path','scopes','principals'})
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
                    or set(principal)-{'id','token_env','scope','task_id','tools','trusted_usage'}):
                raise ValueError('Invalid principal grant')
            identity=identifier(principal['id']);identifier(principal['task_id'])
            if identity in self.principals or principal['scope'] not in self.policies:raise ValueError('Duplicate or unknown principal scope')
            if type(principal.get('trusted_usage',False)) is not bool:raise ValueError('trusted_usage must be boolean')
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
        with self.store.transaction() as db:
            for scope,policy in self.policies.items():
                row=db.execute('SELECT policy,max_tokens,max_calls FROM governance_scopes WHERE scope=?',(scope,)).fetchone()
                if row and tuple(row)!=(encoded(sorted(policy.get('denied_tools',[]))),policy['max_tokens'],policy['max_model_calls']):
                    raise PolicyDenied('Existing scope policy changed; create a new explicit scope')
            db.execute('CREATE TABLE IF NOT EXISTS remote_run_bindings (run_id TEXT PRIMARY KEY, principal TEXT NOT NULL, task_id TEXT NOT NULL, grant_hash TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS remote_operations (principal TEXT NOT NULL, operation_id TEXT NOT NULL, request_hash TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(principal,operation_id))')

    def authenticate(self,header):
        if not isinstance(header,str) or not header.startswith('Bearer '):raise PolicyDenied('Authentication required')
        fingerprint=hashlib.sha256(header[7:].encode()).digest()
        for expected,identity in self.credentials:
            if hmac.compare_digest(fingerprint,expected):return identity
        raise PolicyDenied('Authentication required')

    def _grant_hash(self,principal):
        return hashlib.sha256(encoded({'grant':principal,'policy':self.policies[principal['scope']]}).encode()).hexdigest()

    def _session(self,db,principal,run_id):
        identifier(run_id)
        row=db.execute('SELECT r.*,b.principal,b.task_id,b.grant_hash FROM governance_runs r JOIN remote_run_bindings b ON r.id=b.run_id WHERE r.id=?',(run_id,)).fetchone()
        if (not row or row['principal']!=principal['id'] or row['task_id']!=principal['task_id']
                or row['grant_hash']!=self._grant_hash(principal)):
            raise PolicyDenied('Run unavailable to this principal or grant changed')
        return Session(self.store,self.policies[principal['scope']],run_id,row['owner'])

    def operate(self,principal_id,request):
        principal=self.principals[principal_id]
        if not isinstance(request,dict) or set(request)-{'operation_id','action','data','run_id'} or not {'operation_id','action','data'}<=request.keys():
            raise ValueError('Invalid operation envelope')
        operation_id=identifier(request['operation_id']);action=request['action'];data=request['data']
        if not isinstance(action,str) or not isinstance(data,dict):raise ValueError('Invalid action or data')
        if (action=='begin') == ('run_id' in request):raise ValueError('Only non-begin operations require run_id')
        fingerprint=hashlib.sha256(encoded(request).encode()).hexdigest()
        with self.store.transaction() as db:
            session=None
            if action!='begin':session=self._session(db,principal,request.get('run_id'))
            prior=db.execute('SELECT request_hash,response FROM remote_operations WHERE principal=? AND operation_id=?',
                (principal_id,operation_id)).fetchone()
            if prior:
                if prior['request_hash']!=fingerprint:raise PolicyDenied('Operation ID reused with different parameters')
                if action in {'reserve','tool_started'}:session._active(db)
                return json.loads(prior['response'])
            try:
                result=self._execute(db,principal,session,action,data)
                response={'ok':True,'result':result}
            except (PolicyDenied,BudgetExceeded,ValueError,KeyError) as error:
                if isinstance(error,GovernanceUnavailable):raise
                response={'ok':False,'error_type':type(error).__name__,'message':str(error)}
            # Audit mutations and the idempotent response commit together. A
            # lost HTTP response never causes an untracked second reservation.
            if action not in {'report','inspect'}:
                db.execute('INSERT INTO remote_operations VALUES(?,?,?,?)',
                    (principal_id,operation_id,fingerprint,encoded(response)))
            return response

    def _execute(self,db,principal,session,action,data):
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
            db.execute('INSERT INTO remote_run_bindings VALUES(?,?,?,?)',
                (run_id,principal['id'],principal['task_id'],self._grant_hash(principal)))
            return {'run_id':run_id,'scope':principal['scope'],'lease_seconds':lease}
        if action=='reserve':
            required(data,{'tokens','request_id'})
            return {'request_id':session.reserve(data['tokens'],request_id=identifier(data['request_id']))}
        if action=='tool_started':
            required(data,{'role','tool','action_id'})
            for name in data.values():identifier(name)
            if data['tool'] not in principal['tools'].get(data['role'],[]):
                session.event('authorization_denied',{'principal':principal['id'],'role':data['role'],'tool':data['tool']},action_id=data['action_id'])
                raise PolicyDenied('Tool not granted to this principal and role')
            session.tool_started(data['role'],data['tool'],data['action_id'])
            return {'authorized':True}
        if action=='event':
            required(data,{'kind','payload','action_id'})
            if data['kind'] not in OBSERVATIONS:raise PolicyDenied('Worker cannot publish authoritative control events')
            identifier(data['action_id'])
            session.event('worker_observation',{'principal':principal['id'],'kind':data['kind'],'reported_payload':data['payload'],
                'authority':'worker report, not independent execution proof'},action_id=data['action_id'])
            return {'recorded':True}
        if action=='settle':
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
    parser.add_argument('--ready-file',type=Path,required=True)
    parser.add_argument('--cert',type=Path);parser.add_argument('--key',type=Path)
    args=parser.parse_args()
    if not math.isfinite(args.max_seconds) or args.max_seconds<=0:parser.error('max-seconds must be finite and positive')
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
        while time.monotonic()<deadline:
            server.handle_request()
            if time.monotonic()>=next_progress:
                service.store.reconcile_expired()
                print('[Control service] alive; remaining='+str(round(deadline-time.monotonic(),1))+'s',flush=True)
                next_progress=time.monotonic()+10


if __name__=='__main__':main()
