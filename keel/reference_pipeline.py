"""Bounded reference recovery across compatible stages, with durable provenance."""
import json
import re
import subprocess
import time
from pathlib import Path

from compass.progress import atomic_json
from .evaluation_protocol import file_hash, implementation_hashes
from .swebench import verify_task


def _grade_record(directory, record):
    directory=Path(directory)
    value=json.loads((directory/'grading.json').read_text(encoding='utf-8'))
    if value.get('runtime_status')!='reference_only' or json.loads(
            (directory/'grader-input.json').read_text(encoding='utf-8')) != [record]:
        raise ValueError('Expected reference grading for exactly this frozen task')
    if value.get('report_sha256'):
        reports=list((directory/'logs/run_evaluation').rglob('report.json'))
        if len(reports)!=1 or file_hash(reports[0])!=value['report_sha256']:
            raise ValueError('Official reference report changed or unavailable')
    return value


def _files(directory):
    """Only evidence consumed by recovery, not an unrelated workspace inventory."""
    directory=Path(directory)
    fixed=['grading.json','grader-input.json','plugin-policy.json','network-policy.json',
           'compatibility-policy.json','environment-overlay.json','apt-archives.json']
    paths=[directory/name for name in fixed if (directory/name).is_file()]
    for pattern in ('*/Dockerfile','*/setup_repo.sh','*/build_image.log'):
        paths.extend((directory/'logs/build_images/instances').glob(pattern))
    for name in ('report.json','test_output.txt'):
        paths.extend((directory/'logs/run_evaluation').rglob(name))
    return paths


def recover_pipeline(task, export, failed, output, *, python, timeout=1800,
                     recipe_grade=None, resume=False, grader=None, compatibility=None, cache_inspector=None,
                     apt_archives=None, instance_cache_scope=None, preparation_roots=None):
    """Carry failed reference -> compatibility -> APT retry -> fresh acceptance.

    No source repair, model-generated shell, warnings suppression or task replacement.
    Completed results may be inspected again; interrupted stages are never replayed.
    """
    from .reference_recovery import recover_reference
    from .reference_network_recovery import failure_inputs
    from examples.swebench_bridge import grade
    from examples.run_swebench_task import reference_policies
    if type(timeout) is not int or not 120<=timeout<=7200:
        raise ValueError('Shared reference pipeline deadline must be120..7200seconds')
    task,export,failed,output=map(lambda p:Path(p).resolve(),(task,export,failed,output))
    verify_task(task)
    record=json.loads((task/'grader-dataset.jsonl').read_text(encoding='utf-8'))
    prediction=json.loads((export/'predictions.jsonl').read_text(encoding='utf-8'))
    receipt=json.loads((export/'export-receipt.json').read_text(encoding='utf-8'))
    if (prediction.get('instance_id')!=record['instance_id'] or prediction.get('model_patch')!=record['patch']
            or receipt.get('runtime_status')!='reference_only'
            or receipt.get('predictions_sha256')!=file_hash(export/'predictions.jsonl')
            or receipt.get('task_receipt_sha256')!=file_hash(task/'task-receipt.json')):
        raise ValueError('Require unchanged reference export, never an Agent patch')
    _grade_record(failed,record)
    origin=Path(recipe_grade).resolve() if recipe_grade else failed
    _grade_record(origin,record)
    if instance_cache_scope is not None:
        from .harness_cache import validate_scope
        instance_cache_scope=validate_scope(instance_cache_scope)
    archive_path=Path(apt_archives).resolve() if apt_archives is not None else None
    if archive_path:
        from .apt_archive_bridge import validate_artifact
        validate_artifact(json.loads(archive_path.read_text(encoding='utf-8')))
    inputs={str(p):file_hash(p) for p in [task/'task-receipt.json',task/'grader-dataset.jsonl',
        export/'predictions.jsonl',export/'export-receipt.json',*_files(failed),*_files(origin)]}
    if archive_path:inputs[str(archive_path)]=file_hash(archive_path)
    identity={'task':str(task),'export':str(export),'failed':str(failed),'recipe_grade':str(origin),
              'python':str(python),'timeout':timeout,'inputs':inputs,
              'implementation':implementation_hashes(Path(__file__).resolve().parents[1])}
    if archive_path:identity['apt_archives']=str(archive_path)
    if instance_cache_scope is not None:identity['instance_cache_scope']=instance_cache_scope
    if preparation_roots:
        if archive_path or instance_cache_scope is not None:
            raise ValueError('Choose preparation discovery or explicit asset overrides')
        identity['preparation_roots']=[str(Path(p).resolve()) for p in preparation_roots]
    report_path=output/'pipeline.json'
    if resume:
        report=json.loads(report_path.read_text(encoding='utf-8'))
        if report['identity']!=identity:raise ValueError('Pipeline configuration/input drift')
        for name,expected in report['artifacts'].items():
            if file_hash(Path(name))!=expected:raise ValueError('Completed pipeline artifact changed')
        if report.get('status')=='running' or any(s['status']=='running' for s in report['stages']):
            raise ValueError('Interrupted required stage; preserve and inspect, no automatic redispatch')
        return report
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    report={'status':'running','identity':identity,'stages':[],'artifacts':{},'model_calls':0,
            'reference_grade':None,'benchmark_ready':False,
            'scope':'Registered environment recovery; unchanged task/reference. No source repair or original-condition score.'}
    def save():
        report['seconds']=round(time.monotonic()-started,3)
        atomic_json(report_path,report)
    def check():
        for name,expected in {**inputs,**report['artifacts']}.items():
            if file_hash(Path(name))!=expected:raise ValueError('Pipeline evidence changed: '+name)
        remaining=min(timeout,timeout-(time.monotonic()-started))
        if remaining<=0:raise TimeoutError('Shared reference recovery deadline exhausted')
        return remaining
    grader=grader or grade;compatibility=compatibility or recover_reference
    if cache_inspector is None:
        def cache_inspector(image,seconds):
            value=subprocess.run(['docker','image','inspect','--format','{{.Id}}',image],
                capture_output=True,text=True,check=True,timeout=min(8,seconds)).stdout.strip()
            return value
    current=failed;used=set()
    save()
    try:
        while True:
            remaining=check();old=_grade_record(current,record)
            if old.get('status')=='graded' and old.get('official_resolved') is True:
                reference_policies(current)
                report.update(status='reference_verified',reference_grade=str(current),
                              environment_scope=old.get('environment_scope','original reference conditions'))
                break
            if old.get('status')=='graded':
                action='compatibility'
                if action in used:
                    report.update(status='environment_unresolved',stop_reason='compatibility_revalidation_failed')
                    break
                if remaining<120:raise TimeoutError('Insufficient shared time for compatibility recovery')
                kwargs={'recipe_grade':origin} if origin!=current else {}
            elif old.get('status')=='grading_error':
                # A cold build may have completed just before the overall timeout.
                if 'TimeoutExpired' in old.get('error','') and 'cached_regrade' not in used:
                    from .environment_probe import retained_image
                    image=retained_image(origin)
                    logs=list((origin/'logs/build_images/instances').glob('*/build_image.log'))
                    if len(logs)!=1:raise ValueError('Completed build provenance unavailable')
                    text=logs[0].read_text(encoding='utf-8',errors='replace')
                    match=re.search(r'Successfully built ([a-f0-9]{12,64})',text)
                    if not match or 'Image built successfully!' not in text:
                        raise ValueError('No completed cold-build evidence; no blind rebuild')
                    image_id=cache_inspector(image,remaining)
                    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image_id) or not image_id.startswith('sha256:'+match[1]):
                        raise ValueError('Completed cold-build image absent or changed')
                    action='cached_regrade'
                    kwargs=reference_policies(current)
                    scope=old.get('instance_cache',{}).get('scope')
                    if scope:kwargs['instance_cache_scope']=scope
                    remaining=min(600,check())
                    report['completed_image']={'image':image,'id':image_id,'recipe_grade':str(origin)}
                else:
                    if 'apt_retry' in used:
                        report.update(status='environment_unresolved',stop_reason='registered_apt_retry_already_attempted')
                        break
                    # Reject signatures, altered reference exports, unsupported
                    # sources and a second network policy before dispatch.
                    _,_,script,base,_=failure_inputs(task,export,current,preserve_compatibility=True)
                    action='apt_retry'
                    kwargs=reference_policies(current)
                    if preparation_roots:
                        from .reference_assets import discover_assets
                        report['preparation_discovery']={'status':'running'};save()
                        discovery=discover_assets(preparation_roots,record,current,script,base,
                            inspect_image=cache_inspector,seconds=min(30,check()))
                        report['preparation_discovery']=discovery;save()
                        selected=discovery['selected']
                        if not selected:
                            raise ValueError('No verified preparation matched; no blind rebuild or download')
                        kwargs['apt_archives']=selected['apt_archives']
                        kwargs['instance_cache_scope']=selected['instance_cache_scope']
                        report['artifacts'].update(selected['inputs']);save()
                        remaining=check()
                    if archive_path:
                        from .apt_archive_bridge import validate_artifact
                        from examples.check_repository_network import extract_apt
                        import hashlib
                        artifact=validate_artifact(json.loads(archive_path.read_text(encoding='utf-8')))
                        command=extract_apt(script.read_text(encoding='utf-8'))
                        if artifact['base_image']!=base or artifact['apt_command_sha256']!=hashlib.sha256(command.encode()).hexdigest():
                            raise ValueError('Archive artifact does not match failed APT workload')
                        if 'apt_archives' in kwargs and json.loads(Path(kwargs['apt_archives']).read_text(encoding='utf-8'))!=artifact:
                            raise ValueError('Cannot replace existing archive policy')
                        kwargs['apt_archives']=str(archive_path)
                    kwargs['network_policy']='retry_acquire'
                    scope=old.get('instance_cache',{}).get('scope')
                    if scope and not preparation_roots:kwargs['instance_cache_scope']=scope
                    if instance_cache_scope is not None:kwargs['instance_cache_scope']=instance_cache_scope
            else:
                report.update(status='environment_unresolved',stop_reason='unsupported_reference_status')
                break
            used.add(action)
            directory=output/f'{len(report["stages"])+1}-{action}'
            stage={'action':action,'status':'running','input_grade':str(current),
                   'output':str(directory),'remaining_seconds':remaining}
            report['stages'].append(stage);save()  # Required before any expensive dispatch.
            print(f'[Reference pipeline] {action}; shared remaining={remaining:.0f}s',flush=True)
            if action=='compatibility':
                compatibility(task,export,current,directory,python=python,
                              timeout=max(120,int(remaining)),grader=grader,**kwargs)
                next_grade=directory/'reference-grade'
                if not (next_grade/'grading.json').is_file():
                    recovery=directory/'recovery.json'
                    if recovery.is_file():report['artifacts'][str(recovery)]=file_hash(recovery)
                    stage['status']='completed'
                    report.update(status='environment_unresolved',stop_reason='compatibility_did_not_reach_revalidation')
                    break
            else:
                grader(task,export,directory,python=python,timeout=remaining,**kwargs)
                next_grade=directory
            # Commit a completed stage before selecting its next failure route.
            _grade_record(next_grade,record)
            for path in _files(next_grade):report['artifacts'][str(path)]=file_hash(path)
            recovery=directory/'recovery.json'
            if recovery.is_file():report['artifacts'][str(recovery)]=file_hash(recovery)
            stage.update(status='completed',grade=str(next_grade))
            report['reference_grade']=str(next_grade);save()
            if list((next_grade/'logs/build_images/instances').glob('*/Dockerfile')):
                origin=next_grade
            current=next_grade
    except Exception as error:
        # A dispatched incomplete stage stays running: resuming cannot repeat it.
        report.update(status='environment_unresolved',error_type=type(error).__name__,error=str(error)[:1500])
    finally:
        save()
    return report
