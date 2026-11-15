"""Controller-executed, explicitly catalogued read-only repository tools."""
import hashlib
import json
from pathlib import Path
import stat
import threading

from .core import Budget, Ledger, Limits, PolicyDenied, Trace
from .governance import GovernanceUnavailable, encoded
from .workspace import Workspace


READ_TOOLS=frozenset({'list_files','read_file','read_page','read_lines','search_code'})


class ReadWorkspace(Workspace):
    def __init__(self,*args,allowed,**kwargs):
        self.allowed=frozenset(allowed)
        super().__init__(*args,**kwargs)

    def path(self,relative,write=False):
        if write or relative not in self.allowed:raise PolicyDenied('File not in controller read catalog')
        path=super().path(relative)
        # Reject aliases/links rather than letting one catalog entry name another file.
        if path.relative_to(self.root).as_posix()!=relative:raise PolicyDenied('Read catalog path changed identity')
        info=path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise PolicyDenied('Read catalog requires ordinary unlinked files')
        if info.st_size>1_000_000:raise ValueError('Broker file exceeds 1 MB; prepare a smaller approved source catalog')
        return path

    def files(self):
        total=0
        for name in sorted(self.allowed):
            self.budget.check()
            path=self.path(name);total+=path.stat().st_size
            if total>8_000_000:raise ValueError('Read catalog now exceeds approved byte capacity')
            yield name,path


class ReadToolBroker:
    def __init__(self,service,config):
        if not isinstance(config,dict) or set(config)!={'repositories','evidence_root'}:
            raise ValueError('Broker requires repositories and protected evidence_root')
        self.service=service;self.repositories={};self.policy_hashes={}
        self.evidence=Path(config['evidence_root']).resolve()
        specs=config['repositories']
        if not isinstance(specs,dict) or not specs:raise ValueError('Expected broker task repositories')
        for task,spec in specs.items():
            if (not isinstance(task,str) or not isinstance(spec,dict) or not {'root','files'}<=spec.keys()
                    or set(spec)-{'root','files','writable_files'}):
                raise ValueError('Invalid broker repository specification')
            root=Path(spec['root']).resolve(strict=True);names=spec['files']
            if not root.is_dir() or self.evidence.is_relative_to(root) or service.store.path.is_relative_to(root):
                raise ValueError('Broker evidence and control DB must be outside repository')
            if (not isinstance(names,list) or not 0<len(names)<=128 or any(not isinstance(n,str) for n in names)
                    or len(names)!=len(set(names))):raise ValueError('Expected 1..128 distinct explicit source files')
            # Reuse the runtime path policy even during catalog admission.
            validator=object.__new__(ReadWorkspace);validator.root=root;validator.allowed=frozenset(names)
            total=0
            for name in names:total+=validator.path(name).stat().st_size
            if total>8_000_000:raise ValueError('Broker source catalog exceeds 8 MB')
            writable=spec.get('writable_files',[])
            if (not isinstance(writable,list) or any(not isinstance(n,str) or n not in names for n in writable)
                    or len(writable)!=len(set(writable))):raise ValueError('Writable files must be a unique readable subset')
            for name in writable:Workspace.path(validator,name,write=True)
            self.repositories[task]={'root':root,'files':names,'writable_files':writable}
            policy={'root':str(root),'files':sorted(names)}
            if writable:policy['writable_files']=sorted(writable)
            self.policy_hashes[task]=hashlib.sha256(encoded(policy).encode()).hexdigest()
        # Serialized bounded file observations avoid cross-thread ledger writers.
        self.slot=threading.BoundedSemaphore(1)
        with service.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS broker_read_requests (
                principal TEXT NOT NULL, operation_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                status TEXT NOT NULL, response TEXT, PRIMARY KEY(principal,operation_id))''')

    def capability(self,principal):
        spec=self.repositories.get(principal['task_id'])
        if spec is None:return None
        tools=sorted({name for names in principal['tools'].values() for name in names if name in READ_TOOLS})
        return {'tools':tools,'policy_sha256':self.policy_hashes[principal['task_id']]}

    def execute(self,principal_id,request):
        if (not isinstance(request,dict) or set(request)!={'operation_id','action','run_id','data'}
                or request['action']!='tool_read' or not isinstance(request['operation_id'],str)
                or not 0<len(request['operation_id'])<=256):raise ValueError('Invalid broker envelope')
        principal=self.service.principals[principal_id];data=request['data']
        if not isinstance(data,dict) or set(data)!={'role','tool','args'}:raise ValueError('Invalid broker fields')
        role=data['role'];tool=data['tool'];args=data['args']
        if (not isinstance(role,str) or not isinstance(tool,str) or tool not in READ_TOOLS
                or tool not in principal['tools'].get(role,[]) or principal['task_id'] not in self.repositories):
            raise PolicyDenied('Read tool not granted to principal task/role')
        from .gateway import ToolGateway
        ToolGateway._validate(tool,args)
        if tool=='search_code' and not args['query'].strip():raise ValueError('Search query cannot be empty')
        fingerprint=hashlib.sha256(encoded(request).encode()+self.policy_hashes[principal['task_id']].encode()).hexdigest()
        if not self.slot.acquire(blocking=False):raise GovernanceUnavailable('Read broker busy; no tool dispatch')
        try:
            with self.service.store.transaction() as db:
                session=self.service._session(db,principal,request['run_id'])
                prior=db.execute('SELECT * FROM broker_read_requests WHERE principal=? AND operation_id=?',
                                 (principal_id,request['operation_id'])).fetchone()
                if prior:
                    if prior['request_hash']!=fingerprint:raise PolicyDenied('Read operation ID changed input')
                    if prior['status']!='complete':raise GovernanceUnavailable('Read observation unconfirmed; no implicit redispatch')
                    response=json.loads(prior['response'])
                    if response.get('ok'):response['result']['historical_response']=True
                    return response
                session.tool_started(role,tool,request['operation_id'])
                db.execute('INSERT INTO broker_read_requests VALUES(?,?,?,\'inflight\',NULL)',
                           (principal_id,request['operation_id'],fingerprint))
            try:
                result=self._observe(session,role,tool,args)
                result.update(authority='controller executed read observation',operation_id=request['operation_id'],
                              policy_sha256=self.policy_hashes[principal['task_id']],historical_response=False)
                response={'ok':True,'result':result}
                if len(encoded(response).encode())>240000:raise ValueError('Broker result exceeds transport capacity')
            except Exception as error:
                response={'ok':False,'error_type':'PolicyDenied' if isinstance(error,PolicyDenied) else 'ValueError',
                          'message':'Controller read failed: '+type(error).__name__}
            with self.service.store.transaction() as db:
                # Late completion must not reactivate an expired/finished run.
                self.service.store._event(db,session.run_id,request['operation_id'],'broker_read_outcome',
                    {'role':role,'tool':tool,'completed':response['ok'],
                     'source_hashes':response.get('result',{}).get('source_hashes',{})})
                db.execute("UPDATE broker_read_requests SET status='complete',response=? WHERE principal=? AND operation_id=?",
                           (encoded(response),principal_id,request['operation_id']))
            return response
        finally:self.slot.release()

    def _observe(self,session,role,tool,args):
        # Resolve by authenticated run binding, not by client-selected repository.
        task=self.service.store.runs.remote_task(session._run_grant())
        spec=self.repositories[task]
        folder=self.evidence/session.run_id;folder.mkdir(parents=True,exist_ok=True)
        ledger=Ledger(folder/'reads.sqlite')
        budget=Budget(Limits(max_wallclock=5,max_tool_calls=4,max_tokens=1,max_model_calls=1))
        ws=ReadWorkspace(spec['root'],budget,ledger,Trace(folder/'reads.jsonl'),allowed=spec['files'],memoization=False)
        try:
            before=ws.snapshot()
            if tool=='list_files':payload={'files':sorted(before)}
            elif tool=='search_code':
                payload=ws.search(args['query'],role=role,**({'paths':args['paths']} if 'paths' in args else {}))
            else:
                value=ws.read(args['path'],role=role)['value']
                lines=value.splitlines(keepends=True)
                start=args.get('start_line',1)
                if start>max(1,len(lines)):raise ValueError('Requested line outside source')
                end=min(args.get('end_line',start+79),start+79,len(lines))
                selected=[];size=0
                for line in lines[start-1:end]:
                    if size+len(line)>3000:break
                    selected.append(line);size+=len(line)
                if not selected and lines:raise ValueError('Source line exceeds page capacity')
                last=start+len(selected)-1
                payload={'path':args['path'],'text':''.join(selected),'start_line':start,'end_line':last,
                         'total_lines':len(lines),'next_line':last+1 if last<len(lines) else None,
                         'truncated':last<len(lines),'source_sha256':before[args['path']]}
            if ws.snapshot()!=before:raise ValueError('Source changed during controller observation')
            budget.check()
            fact=ledger.add('symbol' if tool=='search_code' else 'file',role,tool+' controller evidence',payload)
            return {'payload':payload,'source_hashes':before,'controller_fact_id':fact}
        finally:ledger.close()
