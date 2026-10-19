"""Bounded continuation of checkpointed validation; never change its frozen plan."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json, ProgressLog


def observation(run):
    report = json.loads((run/'run.json').read_text(encoding='utf-8'))
    retryable = [r['instance'] for r in report.get('records',[])
        if r.get('status')=='failed' and r.get('stage')=='baseline'
        and ('wall-clock budget exhausted' in r.get('error','') or
             'Index wall-clock budget exhausted' in r.get('error',''))]
    vectors = {}
    for path in run.glob('task-*/index-progress.json'):
        value = json.loads(path.read_text(encoding='utf-8'))
        vectors[path.parent.name] = value.get('vectors_completed',0) or 0
    return dict(status=report['status'],retryable=retryable,vectors=vectors,
        completed=sorted(r['instance'] for r in report.get('records',[]) if r['status']=='completed'))


def has_progress(before,after):
    return (bool(set(after['completed'])-set(before['completed'])) or
        any(value>before['vectors'].get(key,0) for key,value in after['vectors'].items()))


def stop_tree(child):
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],
            capture_output=True,timeout=15)
    if child.poll() is None:
        child.kill()
    child.wait(timeout=15)


def continue_run(plan,run,output,*,rounds=3,timeout=3600,wait_current=False):
    if type(rounds) is not int or not 1<=rounds<=10 or not 1<=timeout<=14400:
        raise ValueError('Require 1-10 rounds and a finite 1-14400 second budget')
    output.mkdir(parents=True,exist_ok=False)
    lock=run/'continuation.lock'
    descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(descriptor,str(os.getpid()).encode());os.close(descriptor)
    started=time.monotonic();deadline=started+timeout
    report=dict(status='running',rounds=[],max_new_rounds=rounds,max_wallclock=timeout,
        plan=str(plan),run=str(run),scope='Additional continuation attempts, not a first-attempt score')
    def save():
        report['elapsed_seconds']=round(time.monotonic()-started,2)
        atomic_json(output/'continuation.json',report)
    try:
        save()
        with ProgressLog(output/'progress.jsonl',console=True,interval=10) as progress:
            if wait_current:
                progress.emit('waiting_for_current_run')
                while observation(run)['status']=='running':
                    if time.monotonic()>=deadline:
                        report.update(status='stopped',reason='Total continuation deadline reached while waiting')
                        return report
                    time.sleep(min(2,max(.01,deadline-time.monotonic())))
            for number in range(1,rounds+1):
                before=observation(run)
                report['last_observation']=before;save()
                if not before['retryable']:
                    report.update(status='finished',reason='No retryable index-budget failures; other exclusions retained')
                    return report
                if before['status']=='running':
                    raise ValueError('Another validation run is active')
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    break
                entry=dict(number=number,before=before,status='running')
                report['rounds'].append(entry);save()
                progress.emit('continuation_round',number=number,retryable=before['retryable'])
                with (output/f'round-{number}.log').open('wb') as log:
                    child=subprocess.Popen([sys.executable,str(Path(__file__).with_name('run_structural_validation.py')),
                        '--plan',str(plan),'--output',str(run),'--execute','--resume'],
                        stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
                    try:
                        child.wait(timeout=remaining)
                    except BaseException:
                        stop_tree(child)
                        raise
                after=observation(run)
                entry.update(status='finished',returncode=child.returncode,after=after,progress=has_progress(before,after))
                report['last_observation']=after;save()
                if child.returncode or not entry['progress']:
                    report.update(status='stopped',reason='Child failure or no checkpoint/completion progress')
                    return report
                if not after['retryable']:
                    report.update(status='finished',reason='No retryable index-budget failures; other exclusions retained')
                    return report
            report.update(status='stopped',reason='Continuation round/time budget exhausted; checkpoints retained')
    except Exception as error:
        report.update(status='stopped',error_type=type(error).__name__,reason=str(error)[:1000])
    finally:
        save();lock.unlink(missing_ok=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',required=True,type=Path)
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--rounds',type=int,default=3)
    parser.add_argument('--timeout',type=int,default=3600)
    parser.add_argument('--wait-current',action='store_true')
    args=parser.parse_args()
    print(json.dumps(continue_run(args.plan.resolve(strict=True),args.run.resolve(strict=True),args.output.resolve(),
        rounds=args.rounds,timeout=args.timeout,wait_current=args.wait_current),indent=2))
