"""Bounded public-task reservation and local commit-availability inventory."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.scout_cohort import reserve_cohort
from keel.scout_tokenizer import file_hash


def execute(plan_path,output,timeout=120):
    plan_path,output=Path(plan_path),Path(output)
    plan=json.loads(plan_path.read_text());started=time.monotonic()
    def remaining():
        value=timeout-(time.monotonic()-started)
        if value<=0:raise TimeoutError('Cohort inventory deadline')
        return value
    def verify():
        for path,sha in plan['inputs'].items():
            remaining()
            if file_hash(path)!=sha:raise ValueError('Cohort input changed')
    verify()
    required=[plan['reservation'],plan['training_export'],*plan['task_files']]
    if any(str(Path(path).resolve()) not in plan['inputs'] for path in required):raise ValueError('Unbound cohort input')
    training=json.loads(Path(plan['training_export']).read_text())
    if file_hash(Path(plan['training_export']).parent/'development.jsonl')!=training['dataset_sha256']:
        raise ValueError('Actual training data changed')
    prior=json.loads(Path(plan['reservation']).read_text())['assignments']['tasks']
    tasks=[json.loads(Path(path).read_text(encoding='utf-8')) for path in plan['task_files']]
    rows=reserve_cohort(tasks,set(training['tasks']),prior,plan['repository_partitions'])
    output.mkdir(parents=True,exist_ok=False)
    report={'status':'running','plan_sha256':file_hash(plan_path),'rows':[],
            'scope':'Exposed development reservation and local commit availability only; no source export, labels, model calls or training',
            'model_calls':0,'weight_updates':0,'production_promoted':False}
    atomic_json(output/'report.json',report)
    try:
        for index,row in enumerate(rows):
            remaining();print(f"[Scout cohort] {index+1}/{len(rows)} {row['instance_id']}",flush=True)
            attempts=[];source=None
            commit=row['base_commit']
            if len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):raise ValueError('Pinned commit required')
            for candidate in plan['source_candidates'].get(row['repo'],[]):
                candidate=Path(candidate).resolve()
                if not candidate.is_relative_to(Path(plan['workspace']).resolve()):raise ValueError('Source outside workspace')
                result=subprocess.run(['git','-c','safe.directory='+candidate.as_posix(),'-C',str(candidate),
                    'cat-file','-t',commit],capture_output=True,text=True,timeout=min(10,remaining()),shell=False)
                available=result.returncode==0 and result.stdout.strip()=='commit'
                attempts.append({'source':str(candidate),'returncode':result.returncode,'commit_available':available})
                if available:source=str(candidate);break
            report['rows'].append({**row,'source_repository':source,'source_status':'commit_available' if source else 'source_unavailable',
                                   'source_attempts':attempts,'source_export_verified':False})
            atomic_json(output/'report.json',report)
        verify()
        report.update(status='reserved_pending_source_export',partitions=dict(Counter(r['partition'] for r in rows)),
                      repository_partitions=plan['repository_partitions'],
                      source_status=dict(Counter(r['source_status'] for r in report['rows'])))
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__);raise
    finally:
        report['seconds']=round(time.monotonic()-started,3);atomic_json(output/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=120)
    args=parser.parse_args();report=execute(args.plan,args.output,args.timeout)
    print(json.dumps({k:report[k] for k in ('status','partitions','source_status','model_calls')}))
