"""Evidence-gated reference recovery followed immediately by independent grading."""
import json
import time
from .environment_probe import inspect_image
from .evaluation_protocol import file_hash
from .harness_plugins import POLICY
from .swebench import verify_task


def recover_reference(task, export, failed, output, *, python, timeout, grader):
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
    if not all(marker in text for marker in ('DeprecationWarning','release-branch-semver','vcs_versioning')):
        raise ValueError('No supported SCM collision failure; no recovery attempted')
    output.mkdir(parents=True,exist_ok=False)
    deadline=time.monotonic()+timeout
    report={'status':'inspecting','benchmark_ready':False,'original_grade_sha256':file_hash(failed/'grading.json'),
            'scope':'One evidence-gated isolated SCM repair and reference revalidation; not agent repair or original-condition score'}
    def save():
        (output/'recovery.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    save()
    try:
        print('[Reference recovery] inspecting plugin providers',flush=True)
        inspection=inspect_image(failed,['setuptools_scm'],['setuptools-scm','vcs-versioning'],timeout=min(45,deadline-time.monotonic()),plugin_probe=True)
        (output/'inspection.json').write_text(json.dumps(inspection,indent=2),encoding='utf-8')
        if inspection.get('returncode')!=0:
            raise ValueError('Plugin inspection did not complete')
        data=json.loads(inspection['stdout'])
        providers={p['distribution'].lower().replace('_','-'):p for p in data.get('providers',[])}
        bad=providers.get('vcs-versioning',{}).get('isolated_call',{})
        good=providers.get('setuptools-scm',{}).get('isolated_call',{})
        if (data.get('baseline',{}).get('passed') is not False or bad.get('error_type')!='DeprecationWarning'
                or good.get('passed') is not True or data.get('dependent_distributions',{}).get('vcs-versioning')!=[]):
            raise ValueError('Collision removal applicability is not established')
        report.update(status='reference_revalidation',plugin_policy=POLICY)
        save()
        print('[Reference recovery] verified collision; applying isolated policy and grading',flush=True)
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise TimeoutError('Recovery deadline exhausted')
        result=grader(task,export,output/'reference-grade',python=python,timeout=remaining,
                      network_policy=old.get('network_policy'),plugin_policy=POLICY)
        report['grading']=result
        report['status']='reference_verified_reconstructed' if result.get('status')=='graded' and result.get('official_resolved') is True else 'environment_unresolved'
    except Exception as error:
        report.update(status='environment_unresolved',error_type=type(error).__name__,error=str(error)[:1500])
    finally:
        save()
    return report
