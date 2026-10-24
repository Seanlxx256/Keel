"""Run one frozen repair attempt under a total wall-clock deadline; never restart it."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.continue_index_validation import stop_tree
from examples.run_swebench_task import implementation_hashes
from keel.evaluation_protocol import file_hash


def execute(plan_path):
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    root = Path(plan['root'])
    if implementation_hashes(root) != plan['implementation']:
        raise ValueError('Frozen implementation changed; prepare a new plan')
    for name, expected in plan.get('input_hashes', {}).items():
        if file_hash(Path(name)) != expected:
            raise ValueError('Frozen input changed: '+name)
    output = Path(plan['output'])
    if output.exists():
        raise ValueError('Output exists; preserve and inspect, do not restart')
    # Child owns its output; watchdog artifacts survive even a forced stop.
    log = plan_path.parent/'console.log'
    receipt = plan_path.parent/'watchdog.json'
    if log.exists() or receipt.exists():
        raise ValueError('Prior dispatch artifacts exist; no automatic retry')
    started = time.monotonic()
    result = {'status': 'dispatching', 'max_seconds': plan['max_seconds'],
              'scope': 'One development continuation; timeout is not a failed acceptance score'}
    receipt.write_text(json.dumps(result, indent=2), encoding='utf-8')
    with log.open('wb') as stream:
        command=[plan['python'],*plan['arguments']]
        job=None
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
        if os.name=='nt':
            from keel.process_job import WindowsJob
            job=WindowsJob();command,options['startupinfo']=job.command(command)
        try:
            child = subprocess.Popen(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT,**options)
        except BaseException:
            if job:job.close()
            raise
        finally:
            if job and job.handle:job.finish_launch()
        try:
            while child.poll() is None:
                if time.monotonic()-started >= plan['max_seconds']:
                    if job:result['cleanup']=job.terminate()
                    stop_tree(child,process_group=os.name!='nt')
                    result['status'] = 'deadline_exceeded'
                    break
                print(f"[Exploration] elapsed={int(time.monotonic()-started)}s; log={log}", flush=True)
                time.sleep(min(10, max(.01, plan['max_seconds']-(time.monotonic()-started))))
            else:
                result['status'] = 'passed' if child.returncode == 0 else 'unresolved'
        finally:
            if job and job.handle:result['cleanup']=job.terminate()
            if child.poll() is None:
                stop_tree(child,process_group=os.name!='nt')
            result.update(returncode=child.poll(), seconds=round(time.monotonic()-started, 3),
                          cleanup_scope='Local containment termination attempted; Docker daemon cleanup is not independently certified')
            receipt.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    raise SystemExit(execute(parser.parse_args().plan.resolve()))
