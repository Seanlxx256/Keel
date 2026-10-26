"""Source-bound, read-only Scout data collection; never approves teacher labels."""
import hashlib
import json
from pathlib import Path
import time

from compass.progress import atomic_json, ProgressLog
from .campaign_reporting import FrozenModel
from .core import Budget, Limits, Ledger, Trace, ModelError
from .localization import localize
from .scout_data_audit import _digest, _hash, _linked
from .swebench import solver_task
from .workspace import Workspace


def task_inputs(plan):
    """Public solver inputs only: private grader records are never opened."""
    reservation=json.loads(Path(plan['reservation']).read_text(encoding='utf-8'))
    exported=json.loads(Path(plan['training_export']).read_text(encoding='utf-8'))
    blocked={key.rsplit('-',1)[0] for key,value in reservation['assignments']['tasks'].items()
             if value['partition'] in ('transfer_review','quarantine')}
    used={row['instance_id'] for row in exported['samples']};seen=set();tasks=[]
    for entry in plan['tasks']:
        task=solver_task(json.loads(Path(entry['solver_task']).read_text(encoding='utf-8')))
        identity=task['instance_id']
        if identity in seen or identity in used:raise ValueError('Duplicate or previously trained collection task')
        if identity.rsplit('-',1)[0] in blocked:raise ValueError('Collection task crosses a reserved repository boundary')
        seen.add(identity);tasks.append((entry,task))
    if not tasks:raise ValueError('Collection needs tasks')
    return tasks


def verify_inputs(plan,check):
    for name,expected in plan['inputs'].items():
        if _hash(Path(name),check)!=expected:raise ValueError('Collection input changed: '+name)
    required=[plan['reservation'],plan['training_export'],plan['model_config'],
              *(entry['solver_task'] for entry in plan['tasks'])]
    if any(str(Path(name).resolve()) not in plan['inputs'] for name in required):raise ValueError('Unbound collection input')


def adopt_cohort_sources(plan_path,cohort_report,output,*,timeout=120):
    """Verify completed exports and create an explicit collection-preparation migration."""
    from compass.preparation import check_archive_snapshot
    plan_path,cohort_report,output=map(lambda p:Path(p).resolve(),(plan_path,cohort_report,output))
    started=time.monotonic()
    def check():
        if time.monotonic()-started>=timeout:raise TimeoutError('Source adoption deadline')
    plan=json.loads(plan_path.read_text());verify_inputs(plan,check);tasks=task_inputs(plan)
    identity=_hash(cohort_report,check)
    if plan['inputs'].get(str(cohort_report))!=identity:raise ValueError('Unbound source adoption report')
    cohort=json.loads(cohort_report.read_text())
    if cohort['status']!='prepared_with_unavailable_sources':raise ValueError('Completed source inventory required')
    by_id={r['instance_id']:r for r in cohort['rows']}
    if len(by_id)!=len(cohort['rows']):raise ValueError('Duplicate source inventory')
    output.mkdir(parents=True,exist_ok=False)
    result={'status':'preparing','plan_sha256':_hash(plan_path,check),'items':[],'model_calls':0,
            'migration':{'source_report':str(cohort_report),'sha256':identity,
                         'scope':'Existing verified source bytes reused; metadata/tree evidence rebuilt, no new Git export'},
            'scope':'Source preparation only; no label approval or model call'}
    atomic_json(output/'preparation.json',result)
    for entry,task in tasks:
        check();row=by_id[task['instance_id']]
        print('[Scout adoption] '+task['instance_id'],flush=True)
        if not row['source_export_verified'] or row['partition']!='training_review':raise ValueError('Unverified or reserved source')
        repo=Path(row['prepared_source']);receipt=check_archive_snapshot(repo,task['base_commit'])
        if (receipt['repository_id']!=task['repo'] or receipt['source']!=str(Path(entry['source_repository']).resolve()) or
            _hash(repo.with_name(repo.name+'.export.json'),check)!=row['receipt_sha256']):raise ValueError('Source adoption identity changed')
        item_output=output/task['instance_id'];item_output.mkdir()
        ledger=Ledger(item_output/'ledger.sqlite')
        try:
            workspace=Workspace(repo,Budget(Limits(max_wallclock=max(1,timeout-(time.monotonic()-started)))),ledger,Trace(item_output/'trace.jsonl'))
            tree=workspace.snapshot();atomic_json(item_output/'tree.json',tree)
        finally:ledger.close()
        result['items'].append({'task':task,'repo':str(repo),'tree_sha256':_digest(tree),
                               'tree_file':str(item_output/'tree.json')})
        atomic_json(output/'preparation.json',result)
    verify_inputs(plan,check)
    if _hash(cohort_report,check)!=identity:raise ValueError('Source report changed during adoption')
    result.update(status='prepared',seconds=round(time.monotonic()-started,3));atomic_json(output/'preparation.json',result)
    return result


class SourceBoundModel:
    """Checkpoint visible catalog source before dispatch; save replies before checks."""
    def __init__(self,model,workspace,output,task):
        self.model,self.workspace,self.output,self.task=model,workspace,Path(output),task
        self.output.mkdir(parents=True,exist_ok=False)
        self.objects=self.output/'objects';self.objects.mkdir()
        self.recorder=FrozenModel(None,None,self.output/'model-transcript.jsonl')
        self.calls=0;self.provider_calls=0

    def __getattr__(self,name):
        method=getattr(self.model,name)
        if name not in ('complete','complete_json') or not callable(method):return method
        def invoke(*args,**kwargs):
            self.workspace.budget.check()
            messages=args[0] if args else kwargs['messages'];schema=kwargs.get('schema')
            if not isinstance(schema,dict) or set(schema.get('properties',{})) not in ({'files'},{'locations'}):
                raise ValueError('Source-bound collector only accepts Scout selection requests')
            payload=json.loads(messages[-1]['content'])
            paths=list(dict.fromkeys([*payload.get('paths',[]),
                *(row['path'] for row in payload.get('structure',[])),
                *payload.get('read_only_evidence_paths',[])]))
            before=self.workspace.snapshot();sources={}
            for path in paths:
                self.workspace.budget.check();target=self.workspace.path(path)
                raw=target.read_bytes();identity=hashlib.sha256(raw).hexdigest()
                if before.get(path)!=identity:raise ValueError('Source changed before capture')
                obj=self.objects/identity
                if obj.exists():
                    if _hash(obj,self.workspace.budget.check)!=identity:raise ValueError('Captured source object changed')
                else:
                    with obj.open('xb') as stream:
                        stream.write(raw);stream.flush()
                        import os
                        os.fsync(stream.fileno())
                sources[path]={'sha256':identity,'bytes':len(raw),'object':str(obj.resolve())}
            if self.workspace.snapshot()!=before:raise ValueError('Repository changed during capture')
            self.calls+=1;call=self.output/('call-'+str(self.calls).zfill(4));call.mkdir()
            atomic_json(call/'tree.json',before)
            binding={'task':self.task,'call_id':self.calls,'source_tree_sha256':_digest(before),
                'catalog_sources':sources,'ledger_fact_ids':[row['fact_id'] for row in self.workspace.ledger.summaries()],
                'training_approved':False,'scope':'Exact pre-call visible catalog bytes plus full visible tree hashes; not semantic approval'}
            atomic_json(call/'source-binding.json',binding)
            from .scout_tokenizer import file_hash
            link={'path':str((call/'source-binding.json').resolve()),'sha256':file_hash(call/'source-binding.json')}
            kwargs=dict(kwargs)
            kwargs['timeout']=min(kwargs['timeout'],self.workspace.budget.remaining)
            self.recorder.record('request',method=name,args=args,kwargs=kwargs,source_binding=link)
            try:
                self.workspace.budget.check();self.provider_calls+=1
                reply=method(*args,**kwargs)
            except Exception as error:
                from .core import ModelCompletionError
                details={}
                if isinstance(error,ModelCompletionError):
                    if isinstance(error.content,str):details['partial_content']=error.content
                    if type(error.tokens) is int and error.tokens>=0:details['tokens']=error.tokens
                self.recorder.record('error',error_type=type(error).__name__,source_binding=link,**details)
                raise
            # Required result is durable even when subsequent source validation fails.
            self.recorder.record('response',content=reply.content,tokens=reply.tokens,
                metadata=getattr(reply,'metadata',None),source_binding=link)
            stable=self.workspace.snapshot()==before
            atomic_json(call/'result.json',{'status':'observed','source_stable':stable,
                'source_binding':link,'training_approved':False})
            if not stable:raise ModelError('Source changed during Scout collection',tokens=reply.tokens)
            return reply
        return invoke


def prepare(plan_path,output,*,timeout=180):
    """Prepare reusable base snapshots only from explicitly named local Git sources."""
    from compass.preparation import prepare_archive_snapshot
    started=time.monotonic();plan_path=Path(plan_path).resolve();output=Path(output).resolve()
    def check():
        if time.monotonic()-started>=timeout:raise TimeoutError('Collection preparation deadline')
    plan=json.loads(plan_path.read_text(encoding='utf-8'));verify_inputs(plan,check);tasks=task_inputs(plan)
    output.mkdir(parents=True,exist_ok=True);receipt=output/'preparation.json'
    if receipt.exists():
        prior=json.loads(receipt.read_text(encoding='utf-8'))
        if prior['plan_sha256']!=_hash(plan_path,check):raise ValueError('Preparation belongs to changed plan')
        if prior['status']=='prepared':
            from compass.preparation import check_archive_snapshot
            if [item['task'] for item in prior['items']]!=[task for _,task in tasks]:raise ValueError('Prepared task inventory mismatch')
            for item in prior['items']:
                check();repo=Path(item['repo']);check_archive_snapshot(repo,item['task']['base_commit'])
                ledger=Ledger(repo.parent/'reuse-ledger.sqlite')
                try:
                    workspace=Workspace(repo,Budget(Limits(max_wallclock=max(1,timeout-(time.monotonic()-started)))),ledger,Trace(repo.parent/'reuse-trace.jsonl'))
                    if _digest(workspace.snapshot())!=item['tree_sha256']:raise ValueError('Completed source preparation changed')
                finally:ledger.close()
            verify_inputs(plan,check)
            return prior
        raise FileExistsError('Incomplete preparation retained; prepare a separate output rather than overwriting its receipt')
    result={'status':'preparing','plan_sha256':_hash(plan_path,check),'items':[],'model_calls':0,
        'scope':'Local base-source preparation only; not new Scout outputs or training labels'}
    atomic_json(receipt,result)
    with ProgressLog(output/'progress.jsonl',console=True) as progress:
        for entry,task in tasks:
            check()
            source=Path(entry['source_repository']).resolve()
            if not source.is_dir() or not (source/'.git').exists():raise ValueError('Explicit local Git source required')
            repo=output/task['instance_id']/'repo'
            try:progress.emit('prepare_source',instance_id=task['instance_id'],completed=len(result['items']),total=len(tasks))
            except OSError:result['telemetry_error']=True
            prepare_archive_snapshot(task['repo'],task['base_commit'],repo,source=str(source),timeout=max(1,timeout-(time.monotonic()-started)))
            ledger=Ledger(repo.parent/'preparation-ledger.sqlite')
            budget=Budget(Limits(max_wallclock=max(1,timeout-(time.monotonic()-started))))
            workspace=Workspace(repo,budget,ledger,Trace(repo.parent/'preparation-trace.jsonl'))
            try:
                tree=workspace.snapshot();atomic_json(repo.parent/'tree.json',tree)
            finally:ledger.close()
            result['items'].append({'task':task,'repo':str(repo.resolve()),'tree_sha256':_digest(tree),
                'tree_file':str((repo.parent/'tree.json').resolve())})
            atomic_json(receipt,result)
    check();verify_inputs(plan,check)
    result.update(status='prepared',seconds=round(time.monotonic()-started,3));atomic_json(receipt,result)
    return result


def evidence_hashes(folder,check):
    files={}
    for path in sorted(folder.rglob('*')):
        check()
        if _linked(path):raise ValueError('Linked collection evidence is not reusable')
        if path.is_file():files[str(path.resolve())]=_hash(path,check)
    return files


def collect(plan_path,prepared,output,*,model=None,resume_from=None):
    plan_path=Path(plan_path).resolve();prepared=Path(prepared).resolve();output=Path(output).resolve()
    plan=json.loads(plan_path.read_text(encoding='utf-8'));budget=Budget(Limits(**plan['budget']))
    verify_inputs(plan,budget.check);tasks=task_inputs(plan)
    prior=None
    if resume_from is not None:
        resume_from=Path(resume_from).resolve()
        prior=json.loads((resume_from/'collection.json').read_text(encoding='utf-8'))
        if prior['plan_sha256']!=_hash(plan_path,budget.check):raise ValueError('Resume plan/configuration changed')
        if [r['instance_id'] for r in prior['tasks']]!=[task['instance_id'] for _,task in tasks]:raise ValueError('Resume task inventory changed')
        for row in prior['tasks']:
            if row['status']=='collected':
                if not row.get('evidence'):raise ValueError('Completed collection lacks evidence receipt')
                for name,expected in row['evidence'].items():
                    path=Path(name)
                    if _linked(path) or not path.resolve().is_relative_to(resume_from) or _hash(path,budget.check)!=expected:
                        raise ValueError('Completed collection evidence changed')
    from .models import from_config
    model=model if model is not None else from_config(json.loads(Path(plan['model_config']).read_text(encoding='utf-8')))
    check_credentials=getattr(model,'check_credentials',None)
    if callable(check_credentials) and (prior is None or any(row['status']!='collected' for row in prior['tasks'])):
        check_credentials() # Before creating any paid-attempt directory.
    receipt=json.loads((prepared/'preparation.json').read_text(encoding='utf-8'))
    if receipt['status']!='prepared' or receipt['plan_sha256']!=_hash(plan_path,budget.check):raise ValueError('Prepared sources do not match plan')
    if [item['task'] for item in receipt['items']]!=[task for _,task in tasks]:raise ValueError('Prepared task inventory mismatch')
    output.mkdir(parents=True,exist_ok=False)
    result={'status':'running','scope':'Scout-only localization collection, no patches/tests/acceptance; all responses require source and semantic review',
        'training_approved':0,'official_resolved':None,'model_config_sha256':plan['inputs'][str(Path(plan['model_config']).resolve())],
        'plan_sha256':_hash(plan_path,budget.check),'tasks':[
            {'instance_id':task['instance_id'],'status':'pending','training_approved':False} for _,task in tasks]}
    if prior is not None:
        result['resume']={'source':str(resume_from),'historical_budget':prior['budget'],
            'scope':'Explicit new attempt; completed tasks reused after evidence/input checks, new calls use a fresh declared budget'}
    def save():
        result['budget']=budget.report();atomic_json(output/'collection.json',result)
    save()
    try:
        with ProgressLog(output/'progress.jsonl',console=True) as progress:
            for index,((_,task),item) in enumerate(zip(tasks,receipt['items'])):
                budget.check();folder=output/task['instance_id'];folder.mkdir()
                atomic_json(folder/'trial.json',{'instance_id':task['instance_id'],'runtime_status':'scout_only','official_resolved':None})
                ledger=Ledger(folder/'ledger.sqlite');workspace=Workspace(Path(item['repo']),budget,ledger,Trace(folder/'trace.jsonl'))
                row=result['tasks'][index];row['status']='collecting';save()
                bound=None;before_cost=budget.report()
                try:
                    if _digest(workspace.snapshot())!=item['tree_sha256']:raise ValueError('Prepared source changed')
                    if prior is not None and prior['tasks'][index]['status']=='collected':
                        row.update(prior['tasks'][index],reused_from=str(resume_from),new_provider_calls=0)
                        continue
                    bound=SourceBoundModel(model,workspace,folder/'capture',task)
                    try:progress.emit('scout_collect',instance_id=task['instance_id'],completed=index,total=len(tasks))
                    except OSError:result['telemetry_error']=True
                    row['selection']=localize(bound,workspace,task['problem_statement'],plan['settings'])
                    row['status']='collected'
                except (ModelError,ValueError) as error:
                    row.update(status='collection_failed',error_type=type(error).__name__)
                finally:
                    ledger.close()
                    if 'reused_from' not in row:
                        row['new_provider_calls']=bound.provider_calls if bound is not None else 0
                        row['attempt_cost']={k:getattr(budget,k)-before_cost[k] for k in ('model_calls','tokens','tool_calls')}
                        row['evidence']=evidence_hashes(folder,budget.check)
                    save()
        verify_inputs(plan,budget.check)
        result['status']='collected_pending_review' if all(row['status']=='collected' for row in result['tasks']) else 'incomplete'
    except Exception as error:
        result.update(status='incomplete',error_type=type(error).__name__);raise
    finally:save()
    return result
