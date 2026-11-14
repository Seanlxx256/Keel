"""Separate HTTP controller and two worker processes, no provider or Docker.

This validates the protocol/process boundary, not OS-level sandbox isolation.
"""
from contextlib import ExitStack
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

from compass.progress import atomic_json
from examples.continue_index_validation import stop_tree
from keel.core import BudgetExceeded, PolicyDenied
from keel.governance import ControlStore
from keel.remote_governance import RemoteSession


def worker(endpoint,task,output):
    session=RemoteSession.begin({'endpoint':endpoint,'token_env':'KEEL_DEMO_WORKER_TOKEN',
        'task_id':task,'timeout_seconds':2},'fixed-worker-protocol-demo',10)
    denied=False
    try:session.tool_started('scout','search_code','forbidden-search')
    except PolicyDenied:denied=True
    session.tool_started('scout','read_file','allowed-read')
    try:
        request=session.reserve(40)
        session.settle(request,0)  # Untrusted self-report must NOT release quota.
        status='reserved'
    except BudgetExceeded:status='quota_denied'
    report={'status':status,'forbidden_search_denied':denied,'run_id':session.run_id,
            'scope':'Control operations only; no model or search actually dispatched.'}
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    atomic_json(Path(output),report)


def execute(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();deadline=started+50  # Reserve up to nine seconds for cleanup.
    env=dict(os.environ)
    env['KEEL_DEMO_A']=secrets.token_urlsafe(32);env['KEEL_DEMO_B']=secrets.token_urlsafe(32)
    config={'path':str(output/'controller/control.sqlite'),
        'scopes':{'demo':{'max_tokens':70,'max_model_calls':5,'lease_seconds':90,'denied_tools':['search_code']}},
        'principals':[{'id':'worker-'+name,'token_env':'KEEL_DEMO_'+name.upper(),'scope':'demo',
                       'task_id':'task-'+name,'tools':{'scout':['read_file','search_code']}} for name in ['a','b']]}
    atomic_json(output/'service.json',config)
    processes=[]
    report={'status':'incomplete','scope':'Separate local processes, not sandbox/cluster certification','model_calls':0}
    try:
        with ExitStack() as stack:
            server_log=stack.enter_context((output/'controller.log').open('wb'))
            options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
            server=subprocess.Popen([sys.executable,'-m','keel.control_service','--config',str(output/'service.json'),
                '--ready-file',str(output/'ready.json'),'--max-seconds','45'],env=env,stdout=server_log,stderr=subprocess.STDOUT,**options)
            processes.append(server)
            print('[Remote governance] starting bounded controller; model calls=0',flush=True)
            ready_deadline=min(deadline,time.monotonic()+10)
            while not (output/'ready.json').is_file():
                if server.poll() is not None:raise RuntimeError('Controller exited; inspect controller.log')
                if time.monotonic()>ready_deadline:raise TimeoutError('Controller startup deadline')
                time.sleep(.1)
            endpoint=json.loads((output/'ready.json').read_text())['endpoint']
            workers=[]
            for name in ['a','b']:
                log=stack.enter_context((output/f'worker-{name}.log').open('wb'))
                # The controller credentials and model credentials are not
                # inherited by either worker. Each receives only its own token.
                child_env={k:v for k,v in os.environ.items() if k.upper() in
                    {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','HOME','PYTHONPATH'}}
                child_env['KEEL_DEMO_WORKER_TOKEN']=env['KEEL_DEMO_'+name.upper()]
                child=subprocess.Popen([sys.executable,'-m','examples.demo_remote_governance','--worker',
                    '--endpoint',endpoint,'--task','task-'+name,'--output',str(output/f'worker-{name}/report.json')],
                    env=child_env,stdout=log,stderr=subprocess.STDOUT,**options)
                workers.append(child);processes.append(child)
            print('[Remote governance] two independent workers; shared token reservation cap=70',flush=True)
            next_progress=time.monotonic()+5
            while any(child.poll() is None for child in workers):
                if time.monotonic()>deadline:raise TimeoutError('Worker deadline')
                if time.monotonic()>next_progress:
                    print('[Remote governance] workers active; elapsed='+str(round(time.monotonic()-started,1))+'s',flush=True)
                    next_progress=time.monotonic()+5
                time.sleep(.1)
            if any(child.returncode for child in workers):raise RuntimeError('Worker failed; preserve worker logs')
            rows=[json.loads((output/f'worker-{name}/report.json').read_text()) for name in ['a','b']]
            if sorted(row['status'] for row in rows)!=['quota_denied','reserved'] or not all(row['forbidden_search_denied'] for row in rows):
                raise AssertionError('Control enforcement did not match the predeclared expected result')
            # This read is operator-side after worker completion; workers were
            # never given a database path or file mount.
            snapshot=ControlStore(output/'controller/control.sqlite',initialize=False).inspect(scope='demo')
            if snapshot['scope']['held']!=40 or snapshot['scope']['calls']!=1:raise AssertionError('Quota accounting mismatch')
            atomic_json(output/'control-evidence.json',snapshot)
            report.update(status='passed',workers=rows,reserved_tokens=40,authorized_model_attempts=1,
                actual_provider_calls=0,identity_boundary='Bearer-authenticated protocol, not filesystem isolation')
    except BaseException as error:
        report.update(error_type=type(error).__name__,message=str(error))
        raise
    finally:
        cleanup=[]
        for child in reversed(processes):
            requested=child.poll() is None
            containment=stop_tree(child,timeout=3,process_group=os.name!='nt') if requested else None
            cleanup.append({'pid':child.pid,'returncode':child.poll(),'termination_requested':requested,
                'containment':containment})
            if child.poll() is None:report['status']='cleanup_unconfirmed'
        report.update(seconds=round(time.monotonic()-started,3),cleanup=cleanup)
        atomic_json(output/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--endpoint');parser.add_argument('--task')
    args=parser.parse_args()
    if args.worker:worker(args.endpoint,args.task,args.output)
    else:
        result=execute(args.output)
        print(json.dumps(result,ensure_ascii=False))
        raise SystemExit(0 if result['status']=='passed' else 1)
