"""One queued Runtime attempt supervised by a separate trusted host process."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from compass.progress import ProgressLog, atomic_json
from .remote_governance import RemoteSession, validate_remote_config


def load_task(path,expected,repo):
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Trusted task config hash mismatch')
    config=json.loads(raw)
    if not isinstance(config,dict):raise ValueError('Expected task object')
    if (config.get('execution') or {}).get('backend')!='docker':
        raise ValueError('Queue worker requires explicit Docker acceptance; no local fallback')
    diagnostic=config.get('diagnostic_execution')
    if diagnostic and diagnostic.get('execution',{}).get('backend')!='docker':
        raise ValueError('Queue worker diagnostics must use Docker')
    if config.get('governance') is not None:
        raise ValueError('Worker host supplies remote governance; remove embedded task governance')
    if not Path(repo).is_dir():raise ValueError('Repository does not exist')
    wallclock=(config.get('budget') or {}).get('max_wallclock')
    if type(wallclock) not in (int,float) or not math.isfinite(wallclock) or wallclock<=0:
        raise ValueError('Task requires a finite positive wall-clock budget')
    return config


def child_environment(remote,allow_env):
    base={'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','HOME'}
    if not isinstance(allow_env,list) or any(not isinstance(key,str) or not key for key in allow_env):
        raise ValueError('Expected trusted environment-name allowlist')
    selected=base|set(allow_env)|{remote['token_env']}
    return {key:value for key,value in os.environ.items() if key in selected}


def execute(*,remote,task_path,task_sha256,repo,output,state_root,max_seconds=600,allow_env=None):
    validate_remote_config(remote)
    if 'state_path' in remote:raise ValueError('Supervisor generates dedicated checkpoint paths')
    if type(max_seconds) not in (int,float) or not math.isfinite(max_seconds) or max_seconds<30:
        raise ValueError('Supervisor budget must be finite and at least 30 seconds')
    repo=Path(repo).resolve();output=Path(output).resolve();state_root=Path(state_root).resolve()
    for path in (output,state_root):
        if path.is_relative_to(repo):raise ValueError('Supervisor evidence/state must be outside task repository')
    config=load_task(task_path,task_sha256,repo)
    env=child_environment(remote,allow_env or [])
    output.mkdir(parents=True,exist_ok=False);state_root.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();deadline=started+max_seconds-10
    lock=state_root/('workspace-'+hashlib.sha256(os.path.normcase(str(repo)).encode()).hexdigest()+'.lock')
    owned=False;session=None;child=None;job=None;cleaned=False
    report={'status':'incomplete','scope':'Trusted single-host supervisor; not sandbox certification'}
    report['cleanup_scope']='Local process containment only; Docker daemon cleanup is not independently certified'
    def cleanup_child():
        nonlocal cleaned
        if cleaned:return
        from examples.continue_index_validation import stop_tree
        cleanup={}
        if job and job.handle:cleanup['job']=job.terminate()
        if child is not None:cleanup['process']=stop_tree(child,timeout=3,process_group=os.name!='nt')
        report['cleanup']=cleanup;cleaned=True
        if (cleanup.get('process',{}).get('root_exited') is False
                or cleanup.get('job',{}).get('tree_signal_sent') is False):
            raise RuntimeError('Local process cleanup unconfirmed; no task completion published')
    try:
        # All workers for a repository must use the same protected state_root.
        with lock.open('x',encoding='utf-8') as stream:
            stream.write(json.dumps({'pid':os.getpid(),'output':str(output)}))
        owned=True
        remote=dict(remote,state_path=str(output/'supervisor-state.json'))
        identity=hashlib.sha256((str(repo)+'\n'+task_sha256).encode()).hexdigest()
        session=RemoteSession.begin(remote,identity,max_seconds)
        claim=session.claim_task();item=claim.get('task')
        if item is None:
            report['status']='idle';return report
        report['claim']={'id':item['id'],'fence':item['fence'],'run_id':session.run_id}
        atomic_json(output/'supervisor.json',report)
        if claim.get('dispatch_allowed') is not True:raise RuntimeError('Historical claim cannot dispatch work')
        if item['payload']!={'task_config_sha256':task_sha256}:
            raise ValueError('Queued payload does not match the trusted worker task; no payload commands accepted')
        confirmed=session.start_task(item['id'],item['fence'])
        if confirmed.get('dispatch_allowed') is not True:raise RuntimeError('Historical start cannot dispatch work')
        remaining=deadline-time.monotonic()
        if remaining<=1:raise TimeoutError('No work time remains')
        config=dict(config)
        config['budget']=dict(config['budget'],max_wallclock=min(config['budget']['max_wallclock'],remaining))
        config['governance']=dict(remote,state_path=str(output/'runtime-state.json'))
        bundle={'repo':str(repo),'output':str(output/'runtime'),'config':config}
        atomic_json(output/'runtime-input.json',bundle)
        command=[sys.executable,'-u','-m','keel.queue_worker','--child',str(output/'runtime-input.json')]
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
        if os.name=='nt':
            from .process_job import WindowsJob
            job=WindowsJob();command,options['startupinfo']=job.command(command)
        code_root=Path(__file__).resolve().parents[1]
        with (output/'runtime-console.log').open('wb') as log:
            try:
                child=subprocess.Popen(command,cwd=code_root,env=env,stdin=subprocess.DEVNULL,
                                       stdout=log,stderr=subprocess.STDOUT,**options)
            finally:
                if job and job.handle:job.finish_launch()
            report.update(status='running',child_pid=child.pid)
            atomic_json(output/'supervisor.json',report)
            with ProgressLog(output/'supervisor-progress.jsonl',console=True,interval=5) as progress:
                progress.emit('runtime_started',pid=child.pid,item=item['id'],fence=item['fence'])
                renew_at=time.monotonic()+30
                while child.poll() is None:
                    if time.monotonic()>=deadline:raise TimeoutError('Supervisor wall-clock budget exhausted')
                    if time.monotonic()>=renew_at:
                        # Failure stops local work; no implicit reconnect/replay.
                        session.renew_task(item['id'],item['fence'])
                        renew_at=time.monotonic()+30
                        progress.emit('lease_renewed',pid=child.pid)
                    time.sleep(min(.2,max(.01,deadline-time.monotonic())))
        report['returncode']=child.returncode
        result_path=output/'runtime/result.json'
        if child.returncode not in (0,1) or not result_path.is_file():
            raise RuntimeError('Runtime exited without a usable result; task outcome uncertain')
        raw=result_path.read_bytes();result=json.loads(raw)
        status=result.get('status')
        if status not in {'passed','failed'}:raise ValueError('Runtime result status is invalid')
        if (child.returncode==0)!=(status=='passed'):raise ValueError('Runtime exit code and result disagree')
        digest=hashlib.sha256(raw).hexdigest()
        cleanup_child()
        report['queue_result']=session.finish_task(item['id'],item['fence'],status=status,artifact_sha256=digest)
        report.update(status='reported_'+status,result_sha256=digest,
                      authority='Worker Runtime report; not controller independent acceptance')
    except Exception as error:
        report.update(status='unresolved',error_type=type(error).__name__,message=str(error))
        # No finish_task on infrastructure loss: leave claimed/running -> unknown.
    finally:
        try:cleanup_child()
        except Exception as error:
            report.update(status='unresolved',cleanup_error_type=type(error).__name__)
        if session is not None:
            try:
                report['governance']=session.finish('passed' if report['status'] in {'idle','reported_passed'} else 'failed')
            except Exception as error:
                report.update(status='unresolved',control_finalization_error=type(error).__name__)
        if owned:
            try:lock.unlink()
            except OSError as error:
                report.update(status='unresolved',lock_cleanup_error=type(error).__name__)
        report['elapsed_seconds']=round(time.monotonic()-started,3)
        atomic_json(output/'supervisor.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child',type=Path)
    parser.add_argument('--plan',type=Path)
    args=parser.parse_args()
    if bool(args.child)==bool(args.plan):parser.error('Choose exactly one of --plan or --child')
    if args.child:
        from .runtime import run
        value=json.loads(args.child.read_text(encoding='utf-8'))
        result=run(value['config'],Path(value['repo']),Path(value['output']))
        return 0 if result['status']=='passed' else 1
    value=json.loads(args.plan.read_text(encoding='utf-8'))
    result=execute(**value)
    print(json.dumps(result))
    return 0 if result['status'] in {'idle','reported_passed'} else 1


if __name__=='__main__':raise SystemExit(main())
