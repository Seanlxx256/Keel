"""Separate frozen development experiment for code/document/config text retrieval."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import load_swe_instance
from compass.preparation import check_snapshot
from compass.progress import atomic_json,ProgressLog
from compass.text_corpus import TextCorpus,POLICY,inventory
from examples.compare_retrieval_alternatives import score
from examples.replay_candidate_interleave import interleave
from examples.run_frozen_retrieval_validation import digest,verify_plan

ARMS=('saved_python_compass','lexical_python','lexical_mixed','compass_plus_text')


def freeze(parent,run,output):
    original=verify_plan(parent,check_implementation=False)
    closed=json.loads((run/'run.json').read_text(encoding='utf-8'))
    if closed['plan_sha256']!=digest(parent):raise ValueError('Original plan/run mismatch')
    if closed['status']=='running':raise ValueError('Original experiment must be stopped')
    output.mkdir(parents=True,exist_ok=False)
    tasks=[];inputs={str(parent.resolve()):digest(parent),str((run/'run.json').resolve()):digest(run/'run.json')}
    for number,task in enumerate(original['tasks'],1):
        dataset=Path(task['dataset']);inputs[str(dataset.resolve())]=digest(dataset)
        runs=run/f'task-{number}/sweep-code-aware/runs.jsonl'
        inputs[str(runs.resolve())]=digest(runs)
        snapshot=Path(__file__).resolve().parents[1]/'.keel/swe-snapshots'/task['repository'].replace('/','--')/task['base_commit']
        tasks.append({**task,'snapshot':str(snapshot),'baseline_runs':str(runs.resolve())})
    files=[Path(__file__),Path(__file__).parents[1]/'compass/text_corpus.py',
           Path(__file__).parents[1]/'compass/lexical.py',Path(__file__).parents[1]/'compass/benchmarks.py',
           Path(__file__).parents[1]/'compass/preparation.py',Path(__file__).parents[1]/'compass/index.py',
           Path(__file__).with_name('compare_retrieval_alternatives.py'),Path(__file__).with_name('replay_candidate_interleave.py')]
    plan=dict(kind='mixed-corpus development extension; original exclusions unchanged',tasks=tasks,
        inputs_sha256=inputs,implementation_sha256={str(p.resolve()):digest(p) for p in files},
        policy=dict(text=POLICY,arms=ARMS,line_budget=100,region_cap=32,
            complement='Alternate original Compass and non-Python text ranks; exact-span deduplication; Compass first',
            lexical_control='Both queries share mixed-index BM25 corpus statistics; only kind filter differs',
            task_timeout=600,index_timeout=300),benchmark_ready=False,
        limitations='Previously exposed five-task development cohort, not held-out. No parameter search. '
            'The saved Python-only control remains partial-corpus on two tasks; original failed statuses are preserved. '
            'Fixed text windows differ from Python symbols. Native Aider/Serena/CocoIndex are not remeasured or '
            'claimed comparable on this new corpus. No LLM calls, embeddings or default promotion.')
    atomic_json(output/'plan.json',plan)
    (output/'plan.sha256').write_text(digest(output/'plan.json')+'\n')
    return dict(status='frozen',tasks=[r['instance_id'] for r in tasks],policy=plan['policy'])


def verify(path):
    if digest(path)!=path.with_suffix('.sha256').read_text().strip():raise ValueError('Plan hash mismatch')
    plan=json.loads(path.read_text())
    for name,expected in {**plan['inputs_sha256'],**plan['implementation_sha256']}.items():
        if digest(Path(name))!=expected:raise ValueError('Frozen input/implementation changed: '+name)
    return plan


def task_run(planpath,output,number):
    plan=verify(planpath);task=plan['tasks'][number-1]
    directory=output/f'task-{number}';directory.mkdir(parents=True,exist_ok=True)
    report=dict(instance=task['instance_id'],status='running',plan_sha256=digest(planpath),stage='input')
    resultpath=directory/'result.json';atomic_json(resultpath,report)
    try:
        root=Path(task['snapshot']);check_snapshot(root,task['base_commit'])
        instance=load_swe_instance(Path(task['dataset']),task['instance_id'],root)
        files,omitted=inventory(root);included={name for name,_ in files}
        missing=sorted(set(instance['core_files'])-included)
        if missing:
            report.update(status='out_of_scope',missing_reference_files=missing)
            atomic_json(resultpath,report);return report
        report['stage']='text_index';atomic_json(resultpath,report)
        with TextCorpus(directory/'text.sqlite') as corpus,ProgressLog(directory/'index-progress.jsonl',console=True) as progress:
            report['index']=corpus.build(root,timeout=plan['policy']['index_timeout'],
                progress=lambda **fields:progress.emit('text_index',**fields))
            missing=sorted(set(instance['core_files'])-corpus.indexed_paths())
            if missing:raise ValueError('Reference files were not indexed: '+repr(missing))
            # Only the issue query, never reference paths/ranges, enters retrieval.
            python=corpus.search(instance['query'],'python')
            mixed=corpus.search(instance['query'])
            text=corpus.search(instance['query'],'text')
        reports=[json.loads(s) for s in Path(task['baseline_runs']).read_text().splitlines() if s.strip()]
        saved=[r for r in reports if r['mode']=='t1' and r['line_budget']==100 and
               r['status'] in ('passed','unindexed_reference_files')]
        if len(saved)!=1:raise ValueError('Missing or ambiguous saved Python-only control')
        old=saved[0]['result']
        if old['instance_id']!=task['instance_id'] or old['base_commit']!=task['base_commit']:
            raise ValueError('Saved control task/commit mismatch')
        primary=[{**r,'start_line':r['start'],'end_line':r['end']} for r in old['candidates']]
        baseline=score(primary,instance)
        if any(abs(value-old['metrics'][key])>1e-12 for key,value in baseline['metrics'].items()):
            raise ValueError('Saved partial-corpus control score does not reproduce')
        arms={'saved_python_compass':baseline,'lexical_python':score(python,instance),
              'lexical_mixed':score(mixed,instance),'compass_plus_text':score(interleave(primary,text),instance)}
        check_snapshot(root,task['base_commit'])
        verify(planpath)
        report.update(status='completed',stage='finished',arms=arms,
            original_control_status=saved[0]['status'],original_unindexed_references=old.get('unindexed_gold_files',[]),
            index_sha256=digest(directory/'text.sqlite'),generation_model_calls=0,embedding_calls=0)
    except Exception as error:
        report.update(status='failed',error_type=type(error).__name__,error=str(error)[:1200])
    atomic_json(resultpath,report);return report


def execute(planpath,output,resume):
    plan=verify(planpath);output.mkdir(parents=True,exist_ok=resume)
    receipt=output/'run.json';previous=json.loads(receipt.read_text()) if receipt.exists() else None
    if previous and previous['plan_sha256']!=digest(planpath):raise ValueError('Resume identity differs')
    records=[]
    for number,task in enumerate(plan['tasks'],1):
        directory=output/f'task-{number}';path=directory/'result.json'
        if path.exists():
            saved=json.loads(path.read_text())
            if saved['status']=='completed':
                prior=[r for r in (previous or {}).get('records',[]) if r['instance']==task['instance_id']]
                if len(prior)!=1 or prior[0]['result_sha256']!=digest(path):raise ValueError('Resume receipt changed')
                if saved['plan_sha256']!=digest(planpath) or digest(directory/'text.sqlite')!=saved['index_sha256']:
                    raise ValueError('Resume index/plan changed')
                check_snapshot(Path(task['snapshot']),task['base_commit'])
                records.append({**saved,'result_sha256':digest(path),'reused':True});continue
            archive=directory/f'prior-{len(list(directory.glob("prior-*.json")))+1}.json';atomic_json(archive,saved)
        directory.mkdir(parents=True,exist_ok=True)
        with (directory/'task.log').open('ab') as log,ProgressLog(directory/'progress.jsonl',console=True) as progress:
            progress.emit('task',instance=task['instance_id'],number=number)
            child=subprocess.Popen([sys.executable,str(Path(__file__)),'--plan',str(planpath),'--output',str(output),
                '--task-number',str(number)],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            try:child.wait(timeout=plan['policy']['task_timeout'])
            except subprocess.TimeoutExpired:
                child.kill();child.wait()
                atomic_json(path,dict(instance=task['instance_id'],status='failed',stage='task_timeout',
                    plan_sha256=digest(planpath),error='Task deadline; text checkpoints retained'))
        if not path.exists():raise ValueError('Worker produced no receipt')
        records.append({**json.loads(path.read_text()),'result_sha256':digest(path)})
        atomic_json(receipt,dict(status='running',plan_sha256=digest(planpath),records=records))
    valid=[r for r in records if r['status']=='completed']
    result=dict(status='completed' if len(valid)==len(records) else 'incomplete',records=records,
        plan_sha256=digest(planpath),planned_tasks=len(records),paired_tasks=len(valid),
        generation_model_calls=0,embedding_calls=0,benchmark_ready=False,default_promoted=False,
        summary={arm:{key:statistics.mean(r['arms'][arm]['metrics'][key] for r in valid) if valid else None
            for key in ('line_recall','line_precision','hit_file_rate')} for arm in ARMS})
    atomic_json(receipt,result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-plan',type=Path)
    parser.add_argument('--parent-run',type=Path)
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--task-number',type=int)
    args=parser.parse_args()
    if args.task_number:
        result=task_run(args.plan.resolve(),args.output.resolve(),args.task_number)
    elif args.execute:
        if not args.plan:parser.error('--execute requires --plan')
        result=execute(args.plan.resolve(),args.output.resolve(),args.resume)
    else:
        if not args.parent_plan or not args.parent_run:parser.error('Freeze requires --parent-plan and --parent-run')
        result=freeze(args.parent_plan.resolve(),args.parent_run.resolve(),args.output.resolve())
    print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))
