"""Known-container identity checks; never prune or delete by name alone."""
import hashlib
import json
import math
import os
import re
import subprocess
import time
import uuid

from .execution import CommandRunner, canonical_mount
from .governance import GovernanceUnavailable, encoded


def owned_container(value,name,expected):
    if not isinstance(value,dict):return False
    identity=value.get('Id','')
    if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity):return False
    if value.get('Name')!='/'+name or value.get('Image')!=expected['image']:return False
    labels=value.get('Labels')
    if not isinstance(labels,dict) or any(labels.get(k)!=v for k,v in expected['labels'].items()):return False
    mounts=value.get('Mounts')
    if not isinstance(mounts,list):return False
    if any(not isinstance(m,dict) or (m.get('Type')=='bind' and type(m.get('RW')) is not bool) for m in mounts):return False
    binds={m.get('Destination'):(canonical_mount(m.get('Source','')),m.get('RW'))
           for m in mounts if isinstance(m,dict) and m.get('Type')=='bind'}
    needed={'/workspace':(canonical_mount(expected['root']),False)}
    if expected['reports'] is not None:needed['/keel-reports']=(canonical_mount(expected['reports']),True)
    return binds==needed


def inspect_known(name,expected,*,remove=False,deadline):
    if not re.fullmatch('keel-[0-9a-f]{32}',name):raise ValueError('Invalid recorded container name')
    def call(args):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Container inspection budget exhausted')
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        return subprocess.run(['docker',*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,timeout=min(2,remaining),**options)
    try:
        # No Config.Env is retrieved or persisted.
        projection='{"Id":{{json .Id}},"Name":{{json .Name}},"Labels":{{json .Config.Labels}},"Image":{{json .Config.Image}},"Mounts":{{json .Mounts}}}'
        response=call(['inspect','--type','container','--format',projection,name])
        if response.returncode:
            listed=call(['container','ls','-a','--no-trunc','--filter','name=^/'+name+'$','--format','{{.ID}}'])
            if listed.returncode==0 and not listed.stdout.strip():return {'name':name,'status':'absent','confirmed_absent':True}
            return {'name':name,'status':'unavailable','confirmed_absent':False}
        value=json.loads(response.stdout)
        if not owned_container(value,name,expected):return {'name':name,'status':'identity_mismatch','confirmed_absent':False}
        if not remove:return {'name':name,'id':value['Id'],'status':'present_owned','confirmed_absent':False}
        removed=call(['rm','--force',value['Id']])  # Full inspected ID, never mutable name.
        listed=call(['container','ls','-a','--no-trunc','--filter','id='+value['Id'],'--format','{{.ID}}'])
        absent=listed.returncode==0 and not listed.stdout.strip()
        return {'name':name,'id':value['Id'],'status':'removed' if absent else 'cleanup_unconfirmed',
                'confirmed_absent':absent,'remove_returncode':removed.returncode}
    except (OSError,ValueError,TypeError,KeyError,TimeoutError,subprocess.TimeoutExpired) as error:
        return {'name':name,'status':'unavailable','confirmed_absent':False,'error_type':type(error).__name__}


class ContainerRegistry:
    def __init__(self,store,owner):
        self.store=store;self.owner=owner
        self.controller=hashlib.sha256(str(store.path).encode()).hexdigest()
        with store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS broker_containers (
                name TEXT PRIMARY KEY, job_id TEXT NOT NULL, owner TEXT NOT NULL,
                expected TEXT NOT NULL, observation TEXT)''')

    def register(self,job_id,name,image,root,reports):
        labels={'io.keel.controller':self.controller,'io.keel.job':job_id,
                'io.keel.owner':self.owner,'io.keel.launch':uuid.uuid4().hex}
        expected={'image':image,'root':str(root),'reports':str(reports) if reports is not None else None,'labels':labels}
        with self.store.transaction() as db:
            db.execute('INSERT INTO broker_containers VALUES(?,?,?,?,NULL)',(name,job_id,self.owner,encoded(expected)))
        return labels

    def inspect_job(self,job_id,*,remove=False,timeout=5):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=30:
            raise ValueError('Container inspection budget must be positive and at most 30 seconds')
        deadline=time.monotonic()+timeout
        with self.store.transaction() as db:
            rows=db.execute('SELECT * FROM broker_containers WHERE job_id=? ORDER BY name',(job_id,)).fetchall()
        observations=[]
        for row in rows:
            observation=(inspect_known(row['name'],json.loads(row['expected']),remove=remove,deadline=deadline)
                         if time.monotonic()<deadline else {'name':row['name'],'status':'not_checked_budget','confirmed_absent':False})
            observation['observed_at']=self.store.clock()
            observations.append(observation)
            with self.store.transaction() as db:
                db.execute('UPDATE broker_containers SET observation=? WHERE name=?',(encoded(observation),row['name']))
        return {'job_id':job_id,'status':'no_recorded_launches' if not rows else 'checked',
                'confirmed_absent':all(v['confirmed_absent'] for v in observations),
                'containers':observations,'scope':'Only recorded container identities, not all daemon resources'}


class TrackedCommandRunner(CommandRunner):
    def __init__(self,config,registry,job_id,stopping):
        super().__init__(config);self.registry=registry;self.job_id=job_id;self.stopping=stopping

    def docker_command(self,command,root,reports,name):
        if self.stopping.is_set():raise GovernanceUnavailable('Executor stopping; no container dispatch')
        args=super().docker_command(command,root,reports,name)
        labels=self.registry.register(self.job_id,name,self.config['image'],root,reports)
        flags=[]
        for key,value in labels.items():flags.extend(['--label',key+'='+value])
        index=len(args)-len(command)-1
        return args[:index]+flags+args[index:]

    def run(self,*args,**kwargs):
        if self.stopping.is_set():raise GovernanceUnavailable('Executor stopping; no command dispatch')
        result=super().run(*args,**kwargs)
        if self.stopping.is_set():raise GovernanceUnavailable('Acceptance cancelled during controller shutdown')
        return result

    def cleanup_timed_out(self,name):
        result=self.registry.inspect_job(self.job_id,remove=True,timeout=5)
        if not result['confirmed_absent']:raise GovernanceUnavailable('Timed out; owned-container cleanup unconfirmed')
