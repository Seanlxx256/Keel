"""Freeze disjoint tasks and compare original Compass, same-pool structure, native Aider."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import load_swe_instance
from compass.coverage import index_coverage
from compass.evaluation_scope import reference_scope, POLICY as SCOPE_POLICY
from compass.index import RepositoryIndex
from compass.preparation import prepare_snapshot
from compass.progress import atomic_json, ProgressLog
from compass.retrieval import Routing
from compass.structural import POLICY, rank_index_structure
from compass.sweep import run_swe_sweep
from keel.core import Limits
from examples.compare_retrieval_alternatives import run as compare, score
from examples.run_frozen_retrieval_validation import (freeze as freeze_base, verify_plan,
    digest, bounded_index, completed_baseline, reuse_baseline)


def freeze(project, output):
    plan = freeze_base(project, output, count=5, seed=20261020)
    plan['kind'] = 'disjoint structural-ranking component validation'
    plan['policy'].update(arms=['code-aware', 'same-pool-structure', 'aider-native-tags'],
        index_coverage='valid-python', structural=POLICY, index_timeout=900,
        task_timeout=1500, aider_timeout=300, aider_version='0.86.2',
        scope_preflight=SCOPE_POLICY,
        structural_pool='exact saved original Compass T1 candidates; no acquisition change')
    for path in [Path(__file__), project/'compass/structural.py',project/'compass/evaluation_scope.py',
                 Path(__file__).with_name('aider_retrieval_worker.py')]:
        plan['implementation_sha256'][str(path.resolve())] = digest(path)
    plan['limitations'] += ' Structural weights fixed before new task scoring; no tuning or replacement. '
    plan['limitations'] += 'Aider ranking component uses different native candidates, not full Aider Agent.'
    path = output/'plan.json'
    atomic_json(path, plan)
    path.with_suffix('.sha256').write_text(digest(path)+'\n')
    return plan


def task_run(project, plan_path, output, number):
    plan = verify_plan(plan_path)
    task = plan['tasks'][number-1]
    directory = output/f'task-{number}'
    directory.mkdir(parents=True, exist_ok=True)
    report = dict(instance=task['instance_id'], status='running', plan_sha256=digest(plan_path))
    result_path = directory/'result.json'
    atomic_json(result_path, report)
    try:
        policy = plan['policy']
        report['stage'] = 'snapshot'
        atomic_json(result_path, report)
        repo = prepare_snapshot(task['repository'],task['base_commit'],
            project/'.keel/swe-snapshots'/task['repository'].replace('/','--')/task['base_commit'],timeout=60)
        dataset = directory/'instance.jsonl'
        if dataset.exists() and digest(dataset) != task['dataset_sha256']:
            raise ValueError('Existing task data differs')
        dataset.write_bytes(Path(task['dataset']).read_bytes())
        instance = load_swe_instance(dataset,task['instance_id'],repo)
        if policy.get('scope_preflight') == SCOPE_POLICY:
            report['stage'] = 'scope_preflight'
            report['scope_preflight'] = reference_scope(instance)
            atomic_json(result_path,report)
            if not report['scope_preflight']['eligible']:
                report.update(status='out_of_scope',error='Reference files outside declared index scope; no embedding attempted')
                atomic_json(result_path,report)
                return report
        report['stage'] = 'baseline'
        atomic_json(result_path,report)
        if not completed_baseline(directory):
            bounded_index(repo,directory,policy['compass_embedding'],policy['index_timeout'])
            sweep = directory/'sweep-code-aware'
            if sweep.exists():
                raise ValueError('Incomplete baseline sweep retained; inspect before retrying')
            with RepositoryIndex(repo) as index:
                result = run_swe_sweep(index,instance,sweep,modes=('t1',),line_budgets=(100,),repeats=1,
                    seed=plan['seed'],routing=Routing(ranking='code-aware',evidence_policy='read'),
                    limits=Limits(max_wallclock=180,max_tool_calls=100,max_tokens=30000,max_model_calls=4),
                    repository_id=task['repository'],symbol_line_cap=32,coverage_policy='valid-python')
                if not result['all_passed']:
                    raise ValueError('Baseline did not pass coverage/validation; retained sweep')
        source = reuse_baseline(project,task,directory,policy)
        source_path = directory/'source-result.json'
        atomic_json(source_path,{'instances':[source]})
        saved = [json.loads(s) for s in (directory/'sweep-code-aware/runs.jsonl').read_text().splitlines()
                 if s.strip()][0]['result']
        candidates = [{**r,'start_line':r['start'],'end_line':r['end']} for r in saved['candidates']]
        original = score(candidates,instance)
        report['stage'] = 'structure'
        atomic_json(result_path,report)
        with RepositoryIndex(repo) as index:
            index.require_fresh()
            structured_rows = rank_index_structure(index,candidates)
            structured = score(structured_rows,instance)
        if {r['id'] for r in structured_rows} != {r['id'] for r in candidates}:
            raise ValueError('Structural arm changed candidate membership')
        report.update(baseline=original['metrics'],structure=structured['metrics'],
            structural_evidence=[dict(id=r['id'],**r['structural_evidence']) for r in structured_rows],
            candidate_count=len(candidates),index_ref=saved['index_ref'])
        report['stage'] = 'aider'
        atomic_json(result_path,report)
        # Each failed native attempt gets a fresh directory; prior results remain.
        attempt = 1
        while (directory/f'aider-{attempt}').exists():
            attempt += 1
        measured = compare(source_path,directory/f'aider-{attempt}', engines=('aider_native_tags',),
            aider_python=project/'.keel/tools/aider-retrieval-venv/Scripts/python.exe',
            engine_timeout=policy['aider_timeout'],
            resume_report=directory/f'aider-{attempt-1}/comparison.json'
                if attempt>1 and (directory/f'aider-{attempt-1}/comparison.json').exists() else None)
        native = next(r for r in measured['records'] if r['engine']=='aider_native_tags')
        report['aider_status'] = native['status']
        if native['status'] != 'ok':
            report['aider_error'] = native.get('detail')
            raise ValueError('Aider unavailable/failed; partial Compass scores retained')
        if native['version'] != policy['aider_version']:
            raise ValueError('Native Aider version differs from frozen plan')
        artifacts = [directory/'sweep-code-aware/runs.jsonl',source_path,
                     directory/f'aider-{attempt}/comparison.json']
        report.update(aider=native['metrics'],status='completed',stage='finished',
            artifact_hashes={str(p.resolve()):digest(p) for p in artifacts})
    except Exception as error:
        report.update(status='failed',error_type=type(error).__name__,error=str(error)[:1200])
    atomic_json(result_path,report)
    return report


def execute(project,plan_path,output,resume=False):
    plan = verify_plan(plan_path)
    output.mkdir(parents=True,exist_ok=resume)
    receipt = output/'run.json'
    prior = json.loads(receipt.read_text()) if receipt.exists() else None
    if prior and prior['plan_sha256'] != digest(plan_path):
        raise ValueError('Resume plan identity differs')
    records = []
    for number,task in enumerate(plan['tasks'],1):
        directory = output/f'task-{number}'
        path = directory/'result.json'
        if path.exists():
            old = json.loads(path.read_text())
            if old['plan_sha256'] != digest(plan_path) or old['instance'] != task['instance_id']:
                raise ValueError('Task receipt identity differs')
            if old['status']=='completed':
                historical = [r for r in (prior or {}).get('records',[]) if r['instance']==task['instance_id']]
                if len(historical)!=1 or historical[0].get('result_sha256') != digest(path):
                    raise ValueError('Completed task receipt changed or is not checkpointed')
                if any(digest(Path(p))!=expected for p,expected in old['artifact_hashes'].items()):
                    raise ValueError('Completed task artifacts changed')
                reuse_baseline(project,task,directory,plan['policy'])
                records.append({**old,'result_sha256':digest(path),'reused':True})
                atomic_json(receipt,dict(status='running',plan_sha256=digest(plan_path),records=records))
                continue
            atomic_json(directory/f'prior-result-{len(list(directory.glob("prior-result-*.json")))+1}.json',old)
        directory.mkdir(parents=True,exist_ok=True)
        with (directory/'task.log').open('ab') as log, ProgressLog(directory/'progress.jsonl',console=True) as progress:
            progress.emit('task',instance=task['instance_id'],number=number,log=str(directory/'task.log'))
            child = subprocess.Popen([sys.executable,str(Path(__file__)),'--plan',str(plan_path),
                '--output',str(output),'--task-number',str(number)],stdout=log,stderr=subprocess.STDOUT)
            try:
                child.wait(timeout=plan['policy']['task_timeout'])
            except subprocess.TimeoutExpired:
                child.kill(); child.wait()
                atomic_json(path,dict(instance=task['instance_id'],status='failed',stage='task_timeout',
                    plan_sha256=digest(plan_path),error='Task wall-clock exhausted; checkpoints retained'))
        if not path.exists():
            raise ValueError('Child did not write a task receipt')
        records.append({**json.loads(path.read_text()),'result_sha256':digest(path)})
        atomic_json(receipt,dict(status='running',plan_sha256=digest(plan_path),records=records))
    completed = [r for r in records if r['status']=='completed']
    report = dict(status='completed' if len(completed)==len(records) else 'incomplete',
        plan_sha256=digest(plan_path),records=records,paired_tasks=len(completed),planned_tasks=len(records),
        generation_model_calls=0,benchmark_ready=False,default_promoted=False,
        summary={arm:{key:statistics.mean(r[arm][key] for r in completed) if completed else None
            for key in ('line_recall','line_precision','hit_file_rate')} for arm in ('baseline','structure','aider')})
    atomic_json(receipt,report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--task-number',type=int)
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[1]
    if args.task_number:
        if not args.plan:
            parser.error('--task-number requires --plan')
        result=task_run(project,args.plan.resolve(),args.output.resolve(),args.task_number)
    elif args.execute:
        if not args.plan:
            parser.error('--execute requires --plan')
        result=execute(project,args.plan.resolve(),args.output.resolve(),args.resume)
    else:
        if args.plan or args.resume:
            parser.error('Freezing does not accept --plan/--resume')
        result=freeze(project,args.output.resolve())
    print(json.dumps(result,indent=2))
