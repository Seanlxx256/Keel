"""Bridge frozen reference APT failures to bounded transport recovery and regrading."""
import json
from pathlib import Path
import re
import subprocess
import time

from .evaluation_protocol import file_hash
from .network_probe import transient_apt_download
from .swebench import verify_task


def failure_inputs(task, export, failed, *, preserve_compatibility=False):
    verify_task(task)
    row=json.loads((task/'grader-dataset.jsonl').read_text(encoding='utf-8'))
    old=json.loads((failed/'grading.json').read_text(encoding='utf-8'))
    if old.get('status')!='grading_error' or old.get('runtime_status')!='reference_only':
        raise ValueError('Require failed reference infrastructure grading')
    if json.loads((failed/'grader-input.json').read_text(encoding='utf-8')) != [row]:
        raise ValueError('Failed grading belongs to a different frozen task')
    receipt=json.loads((export/'export-receipt.json').read_text(encoding='utf-8'))
    prediction=json.loads((export/'predictions.jsonl').read_text(encoding='utf-8'))
    if (receipt.get('runtime_status')!='reference_only' or receipt['task_receipt_sha256']!=file_hash(task/'task-receipt.json')
            or receipt['predictions_sha256']!=file_hash(export/'predictions.jsonl')
            or prediction.get('instance_id')!=row['instance_id'] or prediction.get('model_patch')!=row['patch']):
        raise ValueError('Require unchanged reference export, never an Agent patch')
    if old.get('network_policy') or old.get('environment_overlay_sha256'):
        raise ValueError('Do not stack recovery policies')
    policy_inputs=[]
    if old.get('plugin_policy') or old.get('compatibility_policy_sha256') or old.get('apt_archives_sha256'):
        if not preserve_compatibility:
            raise ValueError('Existing compatibility policies require explicit preservation')
        if old.get('plugin_policy'):
            from .harness_plugins import POLICY
            path=failed/'plugin-policy.json'
            if (old['plugin_policy']!=POLICY or file_hash(path)!=old.get('plugin_policy_sha256')
                    or json.loads(path.read_text(encoding='utf-8'))!={'policy':POLICY,'version':1}):
                raise ValueError('Prior plugin policy changed')
            policy_inputs.append(path)
        if old.get('apt_archives_sha256'):
            from .apt_archive_bridge import validate_artifact
            path=failed/'apt-archives.json'
            if file_hash(path)!=old['apt_archives_sha256']:raise ValueError('Prior archive artifact changed')
            validate_artifact(json.loads(path.read_text(encoding='utf-8')))
            policy_inputs.append(path)
        if old.get('compatibility_policy_sha256'):
            from .dependency_compatibility import validate_policy
            path=failed/'compatibility-policy.json'
            if file_hash(path)!=old['compatibility_policy_sha256']:
                raise ValueError('Prior compatibility policy changed')
            validate_policy(json.loads(path.read_text(encoding='utf-8')))
            policy_inputs.append(path)
    entries=[]
    for log in (failed/'logs/build_images/instances').glob('*/build_image.log'):
        if log.parent.name.startswith('sweb.eval.x86_64.'+row['instance_id']+'__'):
            entries.append(log)
    if len(entries)!=1:
        raise ValueError('Require one matching instance build failure')
    log=entries[0];script=log.with_name('setup_repo.sh');dockerfile=log.with_name('Dockerfile')
    for path in (log,script,dockerfile):
        if path.is_symlink() or not path.resolve().is_relative_to(failed.resolve()):
            raise ValueError('Build artifact escapes failed grading')
    text=log.read_text(encoding='utf-8',errors='replace')
    if not transient_apt_download(text):
        raise ValueError('No supported transient APT download failure')
    source=script.read_text(encoding='utf-8')
    if 'git reset --hard '+row['base_commit'] not in source:
        raise ValueError('Setup script does not match frozen base commit')
    from examples.check_repository_network import extract_apt
    extract_apt(source)  # Allow only registered update/upgrade/install command chain.
    match=re.search(r'^FROM(?: --platform=\S+)? (sweb\.env\.[A-Za-z0-9._-]+:[A-Za-z0-9._-]+)\s*$',dockerfile.read_text(encoding='utf-8'),re.M)
    if not match:
        raise ValueError('Require named official local environment image')
    return row,old,script,match[1],[task/'task-receipt.json',failed/'grading.json',failed/'grader-input.json',export/'predictions.jsonl',export/'export-receipt.json',log,script,dockerfile,*policy_inputs]


def recover_reference_network(task,export,failed,output,model,*,python,timeout=1800,max_steps=4,grader=None,workload=None,network_recover=None,image_identity=None,preserve_compatibility=False,bridge_archives=False,archive_exporter=None):
    if type(timeout) is not int or not 900<=timeout<=7200 or type(max_steps) is not int or not 1<=max_steps<=6:
        raise ValueError('Recovery requires900..7200seconds and1..6model steps')
    row,old,script,image,inputs=failure_inputs(task,export,failed,preserve_compatibility=preserve_compatibility)
    hashes={str(p):file_hash(p) for p in inputs}
    if grader is None:
        from examples.swebench_bridge import grade
        grader=grade
    if workload is None:
        from examples.check_repository_network import apt_workload
        workload=apt_workload
    if network_recover is None:
        from .network_recovery import recover_network
        network_recover=recover_network
    if image_identity is None:
        def image_identity(name):
            return subprocess.run(['docker','image','inspect','--format','{{.Id}}',name],capture_output=True,text=True,check=True,timeout=10).stdout.strip()
    output.mkdir(parents=True,exist_ok=False)
    deadline=time.monotonic()+timeout
    report={'status':'inspecting','instance_id':row['instance_id'],'benchmark_ready':False,'model_calls':0,'original_inputs':hashes,
        'scope':'Separate environment recovery; original failed task/result retained. No source, test, package list, signature or host configuration changes.'}
    def save():
        (output/'recovery.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    def remaining():
        return min(timeout,deadline-time.monotonic())
    def check():
        if any(file_hash(Path(p))!=v for p,v in hashes.items()):
            raise ValueError('Recovery input changed')
        if remaining()<=0:
            raise TimeoutError('Shared environment recovery deadline exhausted')
        if image_identity(image)!=identity:
            raise ValueError('Base image identity changed')
    save()
    try:
        identity=image_identity(image)
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',identity):
            raise ValueError('Invalid local base image identity')
        report.update(image=image,base_image_id=identity,status='retrying_original_apt')
        save();check()
        print('[Reference network] retry original APT workload; reserve final grading time',flush=True)
        initial=output/'apt-original';initial.mkdir()
        # Keep 600s for fresh grading and 60s for identity/cleanup/dispatch overhead.
        # A growing package install may borrow unused diagnosis time, never grading time.
        report['original_stage_policy']={'soft_seconds':600,'extension_seconds':120,
            'freshness_seconds':120,'phase_grace_seconds':240,'reserved_seconds':660}
        save()
        observed=workload(script,image,initial,int(remaining())-660,attempts=1,transport='original',
                          progress_budget={'soft_seconds':600,'extension_seconds':120,'freshness_seconds':120,
                                           'phase_grace_seconds':240})
        report['original_workload']=observed;save();check()
        policy=None
        if observed.get('status')=='apt_failed':
            available=int(remaining())-600
            if available<90:
                raise TimeoutError('Insufficient diagnosis budget after reserving regrading')
            report['status']='network_diagnosis';save()
            from .campaign_reporting import FrozenModel
            recorder=FrozenModel(model,check,output/'model-transcript.jsonl')
            react=output/'network-react';react.mkdir()
            diagnosis=network_recover(initial,script,image,react,recorder,workload,timeout=min(900,available),max_steps=max_steps)
            report['network_diagnosis']=diagnosis
            report['model_calls']=diagnosis.get('budget',{}).get('model_calls',0)
            save();check()
            if diagnosis.get('status')!='apt_recovered_under_transport_policy':
                report['status']='environment_unresolved'
                return report
            policy='no_pipeline'
        elif observed.get('status')!='apt_completed':
            report['status']='environment_unresolved'
            report['stop_reason']=observed.get('stop_reason') or observed.get('status')
            return report
        report.update(status='reference_revalidation',network_policy=policy);save()
        print('[Reference network] workload completed; independently regrade unchanged reference',flush=True)
        check()
        kwargs={'network_policy':policy} if policy else {}
        if old.get('plugin_policy'):kwargs['plugin_policy']=old['plugin_policy']
        if old.get('compatibility_policy_sha256'):
            kwargs['compatibility_policy']=json.loads((failed/'compatibility-policy.json').read_text(encoding='utf-8'))
        if old.get('apt_archives_sha256'):
            kwargs['apt_archives']=json.loads((failed/'apt-archives.json').read_text(encoding='utf-8'))
        if bridge_archives and 'apt_archives' not in kwargs:
            from .apt_archive_bridge import export_archives
            candidates=[]
            for path in output.rglob('diagnosis.json'):
                if path.is_symlink() or not path.resolve().is_relative_to(output.resolve()):
                    raise ValueError('Archive diagnosis escapes owned output')
                value=json.loads(path.read_text(encoding='utf-8'))
                if value.get('status')=='apt_completed' and value.get('source_sha256')==file_hash(script):
                    candidates.append(path)
            if len(candidates)!=1:raise ValueError('Require one completed owned APT diagnosis for archive export')
            seconds=min(300,int(remaining())-600)
            if seconds<30:raise TimeoutError('Insufficient archive export time after grading reserve')
            report['status']='archive_export';save()
            exported=(archive_exporter or export_archives)(candidates[0],script,output/'archive-export',timeout=seconds)
            report['archive_bridge']=exported;save();check()
            if exported.get('status')!='completed':
                report.update(status='environment_unresolved',stop_reason='archive_export_unavailable_no_blind_redownload')
                return report
            kwargs['apt_archives']=exported['artifact']
        scope=old.get('instance_cache',{}).get('scope')
        if scope:kwargs['instance_cache_scope']=scope
        result=grader(task,export,output/'reference-grade',python=python,timeout=remaining(),**kwargs)
        report['grading']=result
        check()
        passed=result.get('status')=='graded' and result.get('official_resolved') is True
        reconstructed=policy or old.get('plugin_policy') or old.get('compatibility_policy_sha256') or kwargs.get('apt_archives')
        report['status']=('reference_verified_reconstructed' if reconstructed else 'reference_verified') if passed else 'environment_unresolved'
    except Exception as error:
        report.update(status='environment_unresolved',error_type=type(error).__name__)
    finally:
        save()
    return report
