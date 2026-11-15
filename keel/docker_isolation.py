"""Bounded real-Docker isolation validation, with explicit unavailable results."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid

from compass.progress import atomic_json, ProgressLog
from .control_service import ControlService, make_server
from .core import PolicyDenied
from .execution import CommandRunner, canonical_mount
from .governance import GovernedModel, GovernanceUnavailable
from .remote_governance import RemoteSession
from .runtime import run
from .verification_infrastructure import docker_health


PLANNED=['local_image_python','dual_container_boundary','normal_runtime_acceptance',
         'timeout_cleanup','controller_outage']
PROBE_CHECKS={'workspace_read_allowed','non_root','no_effective_capabilities','no_new_privileges',
    'workspace_readonly','root_readonly','only_loopback_interface','external_connect_denied',
    'controller_loopback_unreachable','host_secret_not_in_environment','control_path_unavailable',
    'other_workspace_not_mounted','docker_socket_not_mounted','temporary_write_allowed','reports_write_allowed'}
ROOT=Path(__file__).resolve().parents[1]


class Unavailable(RuntimeError):pass


def source_identity():
    names=['keel/docker_isolation.py','keel/isolation_probe.py','keel/execution.py','keel/runtime.py',
           'keel/governance.py','keel/control_service.py','keel/remote_governance.py',
           'keel/gateway.py','keel/workspace.py','keel/core.py','keel/verification_infrastructure.py',
           'compass/progress.py','examples/validate_docker_isolation.py','examples/continue_index_validation.py']
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def inspect_checks(inspect,repo,reports):
    host=inspect['HostConfig']
    mounts=inspect.get('Mounts',[])
    expected={'/workspace':(canonical_mount(repo),False),'/keel-reports':(canonical_mount(reports),True)}
    # Configured tmpfs may also appear in inspect Mounts, but no extra host bind
    # or named volume is allowed. /tmp is checked through HostConfig separately.
    binds={m['Destination']:(canonical_mount(m['Source']),m['RW']) for m in mounts if m['Type']=='bind'}
    extra=[m for m in mounts if m['Type'] not in {'bind','tmpfs'}]
    return {'running':inspect['State']['Running'] is True,
            'non_root_config':inspect['User']=='65534:65534',
            'network_none':host['NetworkMode']=='none',
            'root_readonly':host['ReadonlyRootfs'] is True,
            'not_privileged':host.get('Privileged') is False,
            'private_pid_mode':host.get('PidMode','')=='',
            'capabilities_dropped':'ALL' in [x.upper() for x in host.get('CapDrop',[])],
            'no_added_capabilities':not host.get('CapAdd'),
            'no_new_privileges':any(x.startswith('no-new-privileges') for x in host.get('SecurityOpt',[])),
            'exact_bind_mounts':binds==expected and not extra,
            'bounded_memory':host['Memory']==256*1024*1024 and host['MemorySwap']==host['Memory'],
            'bounded_processes':host['PidsLimit']==64,
            'bounded_cpu':host['NanoCpus']==1000000000,
            'bounded_tmpfs':'size=64m' in host.get('Tmpfs',{}).get('/tmp','')}


def validate_probe(value,role):
    required=PROBE_CHECKS|({'peer_process_not_addressable'} if role=='a' else set())
    if (not isinstance(value,dict) or value.get('role')!=role or type(value.get('pid')) is not int or value['pid']<=0
            or not isinstance(value.get('checks'),dict) or set(value['checks'])!=required
            or any(type(v) is not bool for v in value['checks'].values())):
        raise ValueError('Probe did not report every required typed check')
    for kind in ['pid','net']:
        if not isinstance(value.get(kind+'_namespace'),str) or not re.fullmatch(kind+r':\[\d+\]',value[kind+'_namespace']):
            raise ValueError('Probe namespace identity missing')
    return value


def reusable_report(output):
    latest=json.loads((output/'latest.json').read_text())
    path=Path(latest['report']).resolve()
    if not path.is_relative_to(output):raise ValueError('Prior report path escapes validation directory')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=latest['report_sha256']:raise ValueError('Prior report hash changed')
    report=json.loads(path.read_text())
    if report['status']!='passed':return None
    if set(report['checks'])!=set(PLANNED) or any(row.get('passed') is not True for row in report['checks'].values()):
        raise ValueError('Prior passed report lacks required checks')
    for name,expected in report['artifact_hashes'].items():
        artifact=(output/name).resolve()
        if not artifact.is_relative_to(output) or hashlib.sha256(artifact.read_bytes()).hexdigest()!=expected:
            raise ValueError('Prior validation artifact changed')
    return {**report,'status':'reused','fresh_execution':False,'source_report':str(path),
            'scope':'Historical completed fixture evidence, hashes checked; no fresh Docker validation.'}


class Validation:
    def __init__(self,output,max_seconds):
        self.output=output;self.deadline=time.monotonic()+max_seconds-20
        self.names=[];self.processes=[];self.command_number=0;self.cleanup=[]

    def remaining(self,cap=60):
        seconds=self.deadline-time.monotonic()
        if seconds<=0:raise TimeoutError('Isolation validation work budget exhausted; cleanup reserved')
        return min(cap,seconds)

    def command(self,args,*,cap=10):
        result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,text=True,
                              timeout=self.remaining(cap),shell=False)
        return result

    def image(self,requested,python):
        # No pull, build, daemon restart, or network/host configuration changes.
        if requested:
            candidates=[requested]
        else:
            result=self.command(['docker','image','ls','--format','{{.ID}} {{.Repository}}:{{.Tag}}'])
            if result.returncode:raise Unavailable('Cannot list local Docker images: '+result.stderr[-1200:])
            rows=[line.split(maxsplit=1) for line in result.stdout.splitlines()]
            rows=sorted(rows,key=lambda row:(not row[1].startswith('python:'),row[1]))
            candidates=list(dict.fromkeys(row[0] for row in rows))[:8]
        failures=[]
        for candidate in candidates:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]*',candidate):raise ValueError('Invalid local image identifier')
            result=self.command(['docker','image','inspect','--format',
                '{{json .Id}}\n{{json .Os}}\n{{json .Config.Entrypoint}}',candidate])
            if result.returncode:
                failures.append({'image':candidate,'stage':'inspect','diagnostic':result.stderr[-800:]});continue
            identity,system,entrypoint=[json.loads(line) for line in result.stdout.strip().splitlines()]
            if system!='linux' or entrypoint:
                failures.append({'image':candidate,'stage':'unsupported_os_or_entrypoint'});continue
            if not re.fullmatch(r'sha256:[a-f0-9]{64}',identity):raise ValueError('Invalid immutable image identity')
            runner=CommandRunner({'backend':'docker','image':identity,'cpus':1,'memory_mb':256,'pids_limit':64})
            root=self.output/'preflight-repo';root.mkdir(exist_ok=True)
            for executable in ([python] if python else ['python3','/opt/miniconda3/envs/testbed/bin/python','python']):
                result=runner.run([executable,'-c','import json,sys; print(json.dumps({"ready":True,"python":sys.executable}))'],root,self.remaining(12))
                atomic_json(self.output/'image-probes.json',{'failed':failures,'last_result':result})
                try:value=json.loads(result['stdout'])
                except ValueError:value={}
                if result['returncode']==0 and value.get('ready') is True and isinstance(value.get('python'),str) and value['python'].startswith('/'):
                    return runner,value['python'],{'image_id':identity,'python':value['python'],'earlier_probes':failures}
                failures.append({'image':identity,'python':executable,'stage':'python_probe','result':result})
        atomic_json(self.output/'image-probes.json',{'failed':failures})
        raise Unavailable('No usable local Linux Python image; supply --image and --python. No image was pulled.')

    def inspect(self,name):
        projection='{"Id":{{json .Id}},"State":{{json .State}},"User":{{json .Config.User}},"HostConfig":{{json .HostConfig}},"Mounts":{{json .Mounts}}}'
        result=self.command(['docker','inspect','--format',projection,name])
        if result.returncode:raise Unavailable('Container inspection unavailable: '+result.stderr[-1200:])
        return json.loads(result.stdout)

    def start(self,runner,command,repo,reports,log):
        name='keel-isolation-'+uuid.uuid4().hex
        self.names.append(name)
        args=runner.docker_command(command,repo.resolve(),reports.resolve(),name)
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
        process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,**options)
        self.processes.append(process)
        return name,process

    def wait_probe(self,process,path):
        deadline=time.monotonic()+self.remaining(25)
        while not path.is_file():
            if process.poll() is not None:raise Unavailable('Probe container exited before writing evidence; inspect container log')
            if time.monotonic()>deadline:raise Unavailable('Probe readiness timeout; not an isolation pass')
            time.sleep(.1)
        return json.loads(path.read_text(encoding='utf-8'))

    def stop_containers(self):
        for name in self.names:
            try:
                result=subprocess.run(['docker','rm','--force',name],capture_output=True,text=True,timeout=5,shell=False)
                confirmed=result.returncode==0 or 'No such container' in result.stderr or 'No such object' in result.stderr
                self.cleanup.append({'name':name,'confirmed_removed':confirmed,'returncode':result.returncode,
                    'diagnostic':result.stderr[-800:] if not confirmed else ''})
            except (OSError,subprocess.TimeoutExpired) as error:
                self.cleanup.append({'name':name,'confirmed_removed':False,'error_type':type(error).__name__})
        self.names=[]
        from examples.continue_index_validation import stop_tree
        for process in self.processes:
            if process.poll() is None:stop_tree(process,timeout=2,process_group=os.name!='nt')
        self.processes=[]


def execute(output,*,image=None,python=None,max_seconds=240,resume=False):
    if type(max_seconds) not in (int,float) or not math.isfinite(max_seconds) or max_seconds<60:
        raise ValueError('Require at least 60 finite seconds including cleanup reserve')
    output=Path(output).resolve()
    identity={'requested_image':image,'requested_python':python,'max_seconds':max_seconds,'implementation':source_identity()}
    if output.exists():
        if not resume:raise ValueError('Output exists; preserve it or explicitly use --resume')
        if json.loads((output/'manifest.json').read_text())!=identity:raise ValueError('Validation inputs/implementation changed; create a new output')
        if (output/'latest.json').is_file():
            reused=reusable_report(output)
            if reused is not None:
                receipts=output/'reuse';receipts.mkdir(exist_ok=True)
                atomic_json(receipts/(uuid.uuid4().hex+'.json'),reused)
                return reused
    else:
        output.mkdir(parents=True);atomic_json(output/'manifest.json',identity)
    attempts=output/'attempts';attempts.mkdir(exist_ok=True)
    attempt=attempts/('attempt-'+uuid.uuid4().hex);attempt.mkdir()
    report={'status':'checking','model_calls':0,'planned_checks':PLANNED,'checks':{},
            'scope':'Real Docker fixture validation; not all container escapes or production certification.',
            'attempt':str(attempt),'earlier_attempts_preserved':True}
    atomic_json(attempt/'report.json',report)
    validation=Validation(attempt,max_seconds)
    server=None;thread=None;secret_keys=[]
    with ProgressLog(attempt/'progress.jsonl',console=True,interval=5) as progress:
        try:
            progress.emit('docker_preflight')
            health=docker_health(timeout=validation.remaining(10))
            atomic_json(attempt/'docker-health.json',health)
            report['docker_health']=health
            if not health['ready']:raise Unavailable('Docker server unavailable: '+health.get('diagnostic',health.get('error_type','unknown')))
            runner,interpreter,environment=validation.image(image,python)
            report['environment']=environment
            report['checks']['local_image_python']={'passed':True,'environment':environment}
            atomic_json(attempt/'report.json',report)
            for role in ['a','b']:
                repo=attempt/('repo-'+role);repo.mkdir()
                (repo/'app.py').write_text('VERSION = 1\n',encoding='utf-8')
                (repo/(role+'_only.txt')).write_text('DISPOSABLE_WORKSPACE_'+role,encoding='utf-8')
                (repo/'probe.py').write_bytes((ROOT/'keel/isolation_probe.py').read_bytes())
                reports=attempt/('reports-'+role);reports.mkdir();reports.chmod(0o777)
            profiles=[]
            for role in ['a','b']:
                key='KEEL_ISOLATION_'+uuid.uuid4().hex.upper();secret_keys.append(key)
                os.environ[key]=secrets.token_urlsafe(32)
                profiles.append({'id':'worker-'+role,'token_env':key,'scope':'isolation',
                    'task_id':'task-'+role,'tools':{'implementer':['replace']}})
            service=ControlService({'path':str(attempt/'controller/control.sqlite'),
                'scopes':{'isolation':{'max_tokens':20000,'max_model_calls':10,'lease_seconds':max_seconds+30}},
                'principals':profiles})
            server=make_server(service);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            endpoint='http://127.0.0.1:'+str(server.server_address[1]);port=server.server_address[1]
            progress.emit('dual_container_boundary',image_id=environment['image_id'])
            with ExitStack() as stack:
                roots={role:attempt/('repo-'+role) for role in ['a','b']}
                folders={role:attempt/('reports-'+role) for role in ['a','b']}
                base=[interpreter,'-u','/workspace/probe.py','--secret-name',secret_keys[0],
                      '--foreign-path',str(service.store.path),'--controller-port',str(port)]
                log=stack.enter_context((attempt/'container-b.log').open('wb'))
                name_b,process_b=validation.start(runner,[*base,'--role','b'],roots['b'],folders['b'],log)
                b=validate_probe(validation.wait_probe(process_b,folders['b']/'probe.json'),'b')
                if not all(b['checks'].values()):
                    report['checks']['dual_container_boundary']={'passed':False,'b':b}
                    raise AssertionError('Container B reported a failed isolation check')
                inspect_b=validation.inspect(name_b)
                log=stack.enter_context((attempt/'container-a.log').open('wb'))
                name_a,process_a=validation.start(runner,[*base,'--role','a','--peer-pid',str(inspect_b['State']['Pid']),
                    '--peer-namespace',b['pid_namespace']],roots['a'],folders['a'],log)
                a=validate_probe(validation.wait_probe(process_a,folders['a']/'probe.json'),'a')
                if not all(a['checks'].values()):
                    report['checks']['dual_container_boundary']={'passed':False,'a':a,'b':b}
                    raise AssertionError('Container A reported a failed isolation check')
                inspect_a=validation.inspect(name_a)
                checks={'a':a,'b':b,'a_config':inspect_checks(inspect_a,roots['a'],folders['a']),
                        'b_config':inspect_checks(inspect_b,roots['b'],folders['b']),
                        'different_pid_namespaces':a['pid_namespace']!=b['pid_namespace'],
                        'different_network_namespaces':a['net_namespace']!=b['net_namespace'],
                        'peer_still_running':validation.inspect(name_b)['State']['Running']}
                atomic_json(attempt/'container-inspection.json',{'a':inspect_a,'b':inspect_b})
                passed=(all(a['checks'].values()) and all(b['checks'].values()) and all(checks['a_config'].values())
                    and all(checks['b_config'].values()) and all(checks[k] for k in ['different_pid_namespaces','different_network_namespaces','peer_still_running']))
                report['checks']['dual_container_boundary']={'passed':passed,**checks}
                atomic_json(attempt/'report.json',report)
                if not passed:raise AssertionError('Docker isolation boundary check failed')
                validation.stop_containers()
                if any(not row['confirmed_removed'] for row in validation.cleanup):
                    raise Unavailable('Probe cleanup unconfirmed; no further containers dispatched')
            progress.emit('normal_runtime_acceptance')
            def normal(role,index):
                budget=validation.remaining(60)
                config={'goal':'Upgrade disposable version','budget':{'max_wallclock':budget},
                    'execution':runner.config,'governance':{'endpoint':endpoint,'token_env':secret_keys[index],
                    'task_id':'task-'+role,'timeout_seconds':2},
                    'acceptance':[[interpreter,'-c','import app; assert app.VERSION == 2; print("ACCEPTANCE_OK")']],
                    'work_items':[{'id':'upgrade','edits':[{'path':'app.py','old':'VERSION = 1','new':'VERSION = 2'}]}]}
                return run(config,attempt/('repo-'+role),attempt/('runtime-'+role))
            results={}
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures={pool.submit(normal,role,index):role for index,role in enumerate(['a','b'])}
                for future in as_completed(futures,timeout=validation.remaining(70)):
                    role=futures[future];result=future.result()
                    results[role]={'status':result['status'],'model_calls':result['budget']['model_calls'],
                        'docker_verification':bool(result['verification']) and all(v.get('backend')=='docker' for v in result['verification']),
                        'source_changed_as_expected':(attempt/('repo-'+role)/'app.py').read_text()=='VERSION = 2\n',
                        'result':str(attempt/('runtime-'+role)/'result.json')}
            passed=all(row['status']=='passed' and row['model_calls']==0 and row['docker_verification']
                       and row['source_changed_as_expected'] for row in results.values()) and len(results)==2
            report['checks']['normal_runtime_acceptance']={'passed':passed,'workers':results}
            atomic_json(attempt/'report.json',report)
            if not passed:raise AssertionError('Normal Docker-backed runtime acceptance failed')
            progress.emit('timeout_cleanup')
            class ObservedRunner(CommandRunner):
                def docker_command(self,command,root,reports,name):
                    self.container_name=name
                    return super().docker_command(command,root,reports,name)
            timed=ObservedRunner(runner.config)
            timeout_dir=attempt/'timeout-report';timeout_dir.mkdir();timeout_dir.chmod(0o777)
            ready=timeout_dir/'started'
            timeout_result=timed.run([interpreter,'-c','from pathlib import Path; import time; Path("/keel-reports/started").write_text("running"); time.sleep(30)'],
                attempt/'repo-a',validation.remaining(10),reports=timeout_dir)
            validation.names.append(timed.container_name)
            removed=validation.command(['docker','inspect',timed.container_name],cap=5)
            absent=removed.returncode!=0 and ('No such' in removed.stderr)
            passed=timeout_result['timeout'] is True and ready.is_file() and absent
            report['checks']['timeout_cleanup']={'passed':passed,'program_started':ready.is_file(),
                'container_absent':absent,'result':timeout_result}
            atomic_json(attempt/'report.json',report)
            if not ready.is_file():raise Unavailable('Timeout hit before the fixture started; no running-process cleanup claim')
            if not passed:raise AssertionError('Timeout cleanup was not established')
            progress.emit('controller_outage')
            session=RemoteSession.begin({'endpoint':endpoint,'token_env':secret_keys[0],'task_id':'task-a','timeout_seconds':.5},'outage-fixture',10)
            server.shutdown();thread.join(timeout=5);server.server_close();server=None
            provider_calls=[]
            class NoProvider:
                def complete(self,*args,**kwargs):provider_calls.append(True);raise AssertionError('Must never dispatch')
            blocked=False
            try:GovernedModel(NoProvider(),session).complete([],timeout=1,max_output=10)
            except GovernanceUnavailable:blocked=True
            report['checks']['controller_outage']={'passed':blocked and not provider_calls,'actual_provider_calls':len(provider_calls)}
            if not report['checks']['controller_outage']['passed']:raise AssertionError('Controller outage failed to block provider dispatch')
            report['status']='passed'
        except Unavailable as error:report.update(status='unavailable',error=str(error))
        except (OSError,subprocess.TimeoutExpired,TimeoutError) as error:
            report.update(status='unavailable',error_type=type(error).__name__,error=str(error))
        except (AssertionError,PolicyDenied,ValueError) as error:
            report.update(status='failed',error_type=type(error).__name__,error=str(error))
        except Exception as error:
            report.update(status='error',error_type=type(error).__name__,error=str(error))
        finally:
            if report['status']=='checking':report['status']='interrupted'
            validation.stop_containers()
            report['cleanup']=validation.cleanup
            if any(not item['confirmed_removed'] for item in validation.cleanup):report['status']='cleanup_unconfirmed'
            if server is not None:server.shutdown();thread.join(timeout=5);server.server_close()
            for key in secret_keys:os.environ.pop(key,None)
            report['artifact_hashes']={str(path.relative_to(output)):hashlib.sha256(path.read_bytes()).hexdigest()
                for path in attempt.rglob('*') if path.is_file() and path.suffix in {'.json','.sqlite','.patch','.py'} and path.name!='report.json'}
            atomic_json(attempt/'report.json',report)
            atomic_json(output/'latest.json',{'report':str(attempt/'report.json'),'status':report['status'],
                'report_sha256':hashlib.sha256((attempt/'report.json').read_bytes()).hexdigest()})
    return report
