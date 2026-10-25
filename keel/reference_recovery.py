"""Evidence-gated reference recovery followed immediately by independent grading."""
import json
import time
import re
from pathlib import Path
from .environment_probe import inspect_image
from .evaluation_protocol import file_hash
from .harness_plugins import POLICY
from .swebench import verify_task
from .environment_probe import DEPENDENCY_PROGRAM,retained_image,run_image_program
from .dependency_compatibility import resolution_request,validate_resolution,RESOLVE_PROGRAM


def recover_reference(task, export, failed, output, *, python, timeout, grader, recipe_grade=None):
    if not 120<=timeout<=7200:
        raise ValueError('Reference recovery deadline must be 120..7200 seconds')
    verify_task(task)
    old=json.loads((failed/'grading.json').read_text(encoding='utf-8'))
    record=json.loads((task/'grader-dataset.jsonl').read_text(encoding='utf-8'))
    if (old.get('runtime_status')!='reference_only' or old.get('status')!='graded'
            or old.get('official_resolved') is not False
            or json.loads((failed/'grader-input.json').read_text(encoding='utf-8')) != [record]):
        raise ValueError('Expected failed reference grading for exactly this frozen task')
    prediction=json.loads((export/'predictions.jsonl').read_text(encoding='utf-8'))
    if prediction.get('instance_id')!=record['instance_id'] or prediction.get('model_patch')!=record['patch']:
        raise ValueError('Recovery requires the reference patch, not an agent prediction')
    logs=list((failed/'logs/run_evaluation').rglob('test_output.txt'))
    if len(logs)!=1:
        raise ValueError('Expected one reference test log')
    text=logs[0].read_text(encoding='utf-8',errors='replace')
    scm_failure=all(marker in text for marker in ('DeprecationWarning','release-branch-semver','vcs_versioning'))
    dependency_failure='ImportError' in text or 'ModuleNotFoundError' in text
    if not scm_failure and not dependency_failure:
        raise ValueError('No supported compatibility failure; no recovery attempted')
    if old.get('compatibility_policy_sha256') or old.get('environment_overlay_sha256'):
        raise ValueError('Do not stack dependency or packaging reconciliations')
    receipt=json.loads((export/'export-receipt.json').read_text(encoding='utf-8'))
    if (receipt['predictions_sha256']!=file_hash(export/'predictions.jsonl')
            or receipt['task_receipt_sha256']!=file_hash(task/'task-receipt.json')):
        raise ValueError('Reference export changed')
    inputs={str(p):file_hash(p) for p in [task/'task-receipt.json',task/'grader-dataset.jsonl',
        export/'export-receipt.json',export/'predictions.jsonl',failed/'grading.json',failed/'grader-input.json',*logs]}
    for key in ('network_policy','plugin_policy'):
        if old.get(key):
            path=failed/(key.replace('_','-')+'.json')
            if file_hash(path)!=old.get(key+'_sha256') or json.loads(path.read_text(encoding='utf-8'))!={'policy':old[key],'version':1}:
                raise ValueError('Prior recovery policy changed')
            inputs[str(path)]=file_hash(path)
    recipe_directory=failed
    if recipe_grade is not None:
        recipe_directory=Path(recipe_grade)
        source_input=recipe_directory/'grader-input.json'
        source_grade=recipe_directory/'grading.json'
        if json.loads(source_input.read_text(encoding='utf-8')) != [record]:
            raise ValueError('Recipe source belongs to a different frozen task')
        if json.loads(source_grade.read_text(encoding='utf-8')).get('runtime_status') != 'reference_only':
            raise ValueError('Recipe source must be a reference grading')
        recipes=list((recipe_directory/'logs/build_images/instances').glob('*/Dockerfile'))
        if len(recipes)!=1 or recipes[0].parent.name.rsplit('__',1)[0] != 'sweb.eval.x86_64.'+record['instance_id']:
            raise ValueError('Expected one matching original reference recipe')
        for path in [source_input,source_grade,*recipes[0].parent.iterdir()]:
            if path.is_symlink():raise ValueError('Recipe source must not contain symlinks')
            if path.is_file():inputs[str(path)]=file_hash(path)
    for path in (recipe_directory/'logs/build_images/instances').glob('*/Dockerfile'):
        inputs[str(path)]=file_hash(path)
    output.mkdir(parents=True,exist_ok=False)
    deadline=time.monotonic()+timeout
    report={'status':'inspecting','benchmark_ready':False,'original_grade_sha256':file_hash(failed/'grading.json'),
            'model_calls':0,'inputs':inputs,'actions':[],'observations':[],
            'scope':'Evidence-gated compatibility recovery and fresh reference grading; not agent repair or original-condition score'}
    if recipe_grade is not None:
        report['recipe_source']={'directory':str(recipe_directory),
            'scope':'Explicit same-task original reference build; cached failure remains the diagnosis source'}
    def save():
        (output/'recovery.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    save()
    def check():
        if any(file_hash(Path(p))!=v for p,v in inputs.items()):
            raise ValueError('Recovery evidence changed')
        remaining=min(timeout,deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Recovery deadline exhausted')
        return remaining
    try:
        plugin_policy=old.get('plugin_policy')
        compatibility=None
        if scm_failure:
            report['observations'].append({'kind':'scm_providers','artifact':'inspection.json','status':'running'})
            save()
            print('[Reference recovery] inspecting plugin providers',flush=True)
            inspection=inspect_image(recipe_directory,['setuptools_scm'],['setuptools-scm','vcs-versioning'],
                                     timeout=min(45,check()),plugin_probe=True,allow_restore=False)
            (output/'inspection.json').write_text(json.dumps(inspection,indent=2),encoding='utf-8')
            report['observations'][-1]['status']='completed'
            if inspection.get('returncode')!=0:raise ValueError('Plugin inspection did not complete')
            data=json.loads(inspection['stdout'])
            providers={p['distribution'].lower().replace('_','-'):p for p in data.get('providers',[])}
            bad=providers.get('vcs-versioning',{}).get('isolated_call',{})
            good=providers.get('setuptools-scm',{}).get('isolated_call',{})
            if (data.get('baseline',{}).get('passed') is not False or bad.get('error_type')!='DeprecationWarning'
                    or good.get('passed') is not True or data.get('dependent_distributions',{}).get('vcs-versioning')!=[]):
                raise ValueError('Collision removal applicability is not established')
            plugin_policy=POLICY
            report['actions'].append({'action':'remove_unused_provider','evidence':'inspection.json','policy':POLICY,'status':'planned'})
            save();check()
        if dependency_failure:
            if check()<540:raise TimeoutError('Reserve300s grading plus bounded inspection/resolution')
            image=retained_image(recipe_directory)
            report['status']='dependency_inspection'
            report['observations'].append({'kind':'dependency_constraints','artifact':'dependencies/result.json','status':'running'})
            save()
            print('[Reference recovery] inspect declared dependency conflicts',flush=True)
            inspection=run_image_program(image,DEPENDENCY_PROGRAM,{},output/'dependencies',timeout=45)
            report['observations'][-1]['status']='completed'
            if inspection.get('returncode')!=0:raise ValueError('Dependency inspection unavailable')
            evidence=json.loads(inspection['stdout'])
            request=resolution_request(evidence,failure_text=text,
                handled_consumers={'vcs-versioning'} if plugin_policy==POLICY else ())
            (output/'dependency-selection.json').write_text(json.dumps(request['scope_evidence'],indent=2),encoding='utf-8')
            report['status']='dependency_resolution'
            report['observations'].append({'kind':'bounded_resolution','artifact':'resolution/result.json','status':'running'})
            save()
            print('[Reference recovery] resolve only conflicted consumers; preserve other versions',flush=True)
            resolution=run_image_program(image,RESOLVE_PROGRAM,request,output/'resolution',timeout=min(180,check()-300),network=True)
            report['observations'][-1]['status']='completed'
            if resolution.get('returncode')!=0:raise ValueError('Isolated dependency resolution unavailable')
            if (not re.fullmatch(r'sha256:[a-f0-9]{64}',inspection.get('base_image_id',''))
                    or inspection.get('base_image_id')!=resolution.get('base_image_id')):
                raise ValueError('Image changed between inspection and resolution')
            compatibility=validate_resolution(request,json.loads(resolution['stdout']))
            (output/'compatibility-policy.json').write_text(json.dumps(compatibility,indent=2),encoding='utf-8')
            report['actions'].append({'action':'reconcile_consumers','evidence':'dependencies/result.json',
                                      'resolution':'resolution/result.json','policy':compatibility,'status':'planned'})
            save();check()
        report.update(status='reference_revalidation',plugin_policy=plugin_policy)
        save()
        print('[Reference recovery] apply verified policies and independently grade',flush=True)
        # Addition/subtraction can round a zero-elapsed deadline above its original budget.
        remaining=check()
        if dependency_failure and remaining<300:raise TimeoutError('Fresh grading reserve depleted')
        if remaining<=0:
            raise TimeoutError('Recovery deadline exhausted')
        kwargs={'network_policy':old.get('network_policy'),'plugin_policy':plugin_policy}
        if compatibility:kwargs['compatibility_policy']=compatibility
        if old.get('instance_cache',{}).get('scope'):
            kwargs['instance_cache_scope']=old['instance_cache']['scope']
        for action in report['actions']:action['status']='submitted_for_revalidation'
        save()
        result=grader(task,export,output/'reference-grade',python=python,timeout=remaining,**kwargs)
        report['grading']=result
        check()
        report['status']='reference_verified_reconstructed' if result.get('status')=='graded' and result.get('official_resolved') is True else 'environment_unresolved'
        for action in report['actions']:
            action['status']='verified_by_reference' if report['status']=='reference_verified_reconstructed' else 'reference_not_accepted'
    except Exception as error:
        report.update(status='environment_unresolved',error_type=type(error).__name__,error=str(error)[:1500])
    finally:
        save()
    return report
