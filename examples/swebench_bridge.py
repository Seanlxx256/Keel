"""Prepare a private benchmark record, export a Keel patch, or invoke official grading."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.evaluation_protocol import file_hash
from keel.swebench import prepare, verify_task, export_prediction, grading_outcome, reference_prediction, validate_harness_schema


def run_harness(command, *, cwd, log_path, timeout, heartbeat=10):
    """Tee unbuffered child output and report liveness even during quiet phases."""
    started = time.monotonic()
    # IOENCODING covers stdio only. UTF8 also covers harness open(..., 'w') logs.
    environment = {**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
    environment.pop('KEEL_HARNESS_ENV_OVERLAY', None)
    environment.pop('KEEL_HARNESS_NETWORK_POLICY', None)
    environment.pop('KEEL_HARNESS_PLUGIN_POLICY', None)
    environment.pop('KEEL_HARNESS_CACHE_SCOPE', None)
    if (cwd/'instance-cache.json').is_file():
        environment['KEEL_HARNESS_CACHE_SCOPE'] = json.loads((cwd/'instance-cache.json').read_text(encoding='utf-8'))['scope']
    if (cwd/'plugin-policy.json').is_file():
        environment['KEEL_HARNESS_PLUGIN_POLICY'] = json.loads((cwd/'plugin-policy.json').read_text(encoding='utf-8'))['policy']
    if (cwd/'network-policy.json').is_file():
        environment['KEEL_HARNESS_NETWORK_POLICY'] = json.loads((cwd/'network-policy.json').read_text(encoding='utf-8'))['policy']
    if (cwd/'environment-overlay.json').is_file():
        environment['KEEL_HARNESS_ENV_OVERLAY'] = str((cwd/'environment-overlay.json').resolve())
    print(f'[SWE-bench] starting; log: {log_path}', flush=True)
    with log_path.open('wb') as stream:
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, shell=False, env=environment)
        (cwd/'harness-process.json').write_text(json.dumps({'pid': process.pid, 'status': 'running',
                                                           'started_at_unix': time.time()}), encoding='utf-8')
        def forward():
            while True:
                chunk = process.stdout.read1(8192)
                if not chunk:
                    break
                stream.write(chunk)
                stream.flush()
                print(chunk.decode('utf-8', errors='replace'), end='', flush=True)
        reader = threading.Thread(target=forward, daemon=True)
        reader.start()
        try:
            while True:
                remaining = timeout-(time.monotonic()-started)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    code = process.wait(timeout=min(heartbeat, remaining))
                    break
                except subprocess.TimeoutExpired:
                    logs = list((cwd/'logs').rglob('*.log')) if (cwd/'logs').exists() else []
                    latest = max(logs, key=lambda path: path.stat().st_mtime) if logs else None
                    detail = f'; latest internal log: {latest}' if latest else '; no internal build log yet'
                    print(f'[SWE-bench +{time.monotonic()-started:.0f}s] process alive; output bytes={stream.tell()}{detail}', flush=True)
            reader.join(timeout=5)
            return subprocess.CompletedProcess(command, code)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            reader.join(timeout=5)
            process.stdout.close()
            (cwd/'harness-process.json').write_text(json.dumps({'pid': process.pid, 'status': 'exited',
                                                               'returncode': process.returncode}), encoding='utf-8')


def grade(task_dir, export_dir, output, *, python=sys.executable, timeout=1800, environment_overlay=None, network_policy=None, plugin_policy=None, instance_cache_scope=None):
    if instance_cache_scope is not None:
        from keel.harness_cache import validate_scope
        validate_scope(instance_cache_scope)
    if type(timeout) not in (int, float) or not 0 < timeout <= 86400:
        raise ValueError('Harness timeout must be positive and at most 86400 seconds')
    if network_policy not in (None, 'no_pipeline') or (network_policy and environment_overlay):
        raise ValueError('Use one registered network policy without stacking packaging overlays')
    if plugin_policy not in (None,'remove_unused_vcs_versioning') or (plugin_policy and environment_overlay):
        raise ValueError('Use registered plugin recovery without packaging overlay stacking')
    task = verify_task(task_dir)
    receipt = json.loads((export_dir/'export-receipt.json').read_text(encoding='utf-8'))
    if (receipt['predictions_sha256'] != file_hash(export_dir/'predictions.jsonl') or
            receipt['task_receipt_sha256'] != file_hash(task_dir/'task-receipt.json')):
        raise ValueError('Export inputs changed')
    output.mkdir(parents=True, exist_ok=False)
    if instance_cache_scope is not None:
        (output/'instance-cache.json').write_text(json.dumps({'scope': instance_cache_scope}), encoding='utf-8')
    if plugin_policy:
        (output/'plugin-policy.json').write_text(json.dumps({'policy':plugin_policy,'version':1}),encoding='utf-8')
    if network_policy:
        (output/'network-policy.json').write_text(json.dumps({'policy':network_policy,'version':1}),encoding='utf-8')
    if environment_overlay is not None:
        from keel.harness_environment import validate_overlay
        validate_overlay(environment_overlay)
        (output/'environment-overlay.json').write_text(json.dumps(environment_overlay, indent=2), encoding='utf-8')
    run_id = 'keel-'+uuid.uuid4().hex
    command = [python, '-u', str(Path(__file__).with_name('swebench_harness_entry.py').resolve()),
               '--dataset_name', str((output/'grader-input.json').resolve()),
               '--predictions_path', str((export_dir/'predictions.jsonl').resolve()),
               '--instance_ids', task['instance_id'], '--max_workers', '1', '--run_id', run_id]
    if environment_overlay is not None or network_policy or plugin_policy or instance_cache_scope:
        command.extend(['--cache_level', 'instance'])
    result = {'status': 'running', 'official_resolved': None, 'runtime_status': receipt['runtime_status'],
              'command': command, 'run_id': run_id, 'benchmark_ready': False, 'timeout_seconds': timeout,
              'transport_adapter': 'LF-only shell/diff/patch writes on Windows; official harness via runpy'}
    if instance_cache_scope is not None:
        result['instance_cache'] = {'scope': instance_cache_scope, 'cache_level': 'instance',
            'identity': 'Session plus generated setup recipe; excludes prediction patch. Test containers and scores remain fresh.'}
    if environment_overlay is not None:
        result['environment_scope'] = 'reconstructed packaging overlay; not unchanged official environment'
        result['environment_overlay_sha256'] = file_hash(output/'environment-overlay.json')
    if network_policy:
        result['network_policy'] = network_policy
        result['network_policy_sha256'] = file_hash(output/'network-policy.json')
        result['environment_scope'] = 'Explicit APT transport adaptation; separate image tag, unchanged source/tests/packages; not original-condition score'
    if plugin_policy:
        result['plugin_policy']=plugin_policy
        result['plugin_policy_sha256']=file_hash(output/'plugin-policy.json')
        result['environment_scope']='Explicit SCM plugin recovery and any declared network adaptation; unchanged source/tests; reconstructed environment, not original-condition score'
    try:
        result['harness_version'] = (importlib.metadata.version('swebench') if python == sys.executable else
            subprocess.run([python, '-c', 'import importlib.metadata; print(importlib.metadata.version("swebench"))'],
                           capture_output=True, text=True, check=True, timeout=20).stdout.strip())
    except importlib.metadata.PackageNotFoundError:
        result['harness_version'] = None
    try:
        row = json.loads((task_dir/'grader-dataset.jsonl').read_text(encoding='utf-8'))
        validate_harness_schema(row, result['harness_version'])
        # JSON arrays work with both classic whole-file and current JSON loaders.
        # The frozen source record stays unchanged; only transport framing differs.
        (output/'grader-input.json').write_text(json.dumps([row]), encoding='utf-8')
        result['grader_input_sha256'] = file_hash(output/'grader-input.json')
        (output/'grading.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        completed = run_harness(command, cwd=output, log_path=output/'harness.log', timeout=timeout)
        result['returncode'] = completed.returncode
        reports = [path for log_dir in ('evaluation', 'run_evaluation')
                   for path in (output/'logs'/log_dir/run_id).glob('*/'+task['instance_id']+'/report.json')]
        if completed.returncode != 0 or len(reports) != 1:
            raise ValueError('Official grading did not produce one report; inspect harness.log')
        result.update(grading_outcome(json.loads(reports[0].read_text(encoding='utf-8')), task['instance_id']))
        result.update(status='graded', report_sha256=file_hash(reports[0]))
    except KeyboardInterrupt:
        result.update(status='interrupted', error='Operator interrupted grading; no official score produced')
        raise
    except Exception as error:
        result.update(status='grading_error', error=f'{type(error).__name__}: {error}')
    finally:
        (output/'grading.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def grade_snapshot(task_dir, repo, reference_dir, output, *, python, timeout):
    """Salvage grading only; never pretend to restore interrupted Agent state."""
    from examples.run_swebench_task import check_reference,reference_policies
    from examples.swebench_verify_workspace import workspace_patch
    import hashlib
    overlay=check_reference(task_dir,reference_dir)
    policies=reference_policies(reference_dir)
    task=verify_task(task_dir)
    patch=workspace_patch(repo,task)
    names=subprocess.run(['git','-c','safe.directory='+repo.as_posix(),'-c','core.autocrlf=false',
        '-C',str(repo),'diff','--name-only','HEAD','--'],capture_output=True,text=True,check=True,timeout=30).stdout.splitlines()
    if not patch.strip() or not names:
        raise ValueError('Saved workspace has no source patch')
    for name in names:
        path=repo/name
        if (not name.endswith('.py') or any(part in ('tests','test','testing','testdata') for part in Path(name).parts)
                or Path(name).name.startswith('test_') or Path(name).name=='conftest.py'
                or path.is_symlink() or not path.resolve().is_relative_to(repo.resolve()) or not path.is_file()):
            raise ValueError('Snapshot grading only admits existing unprotected Python source changes: '+name)
    hashes={name:file_hash(repo/name) for name in names}
    output.mkdir(parents=True,exist_ok=False)
    export=output/'snapshot-export';export.mkdir()
    (export/'predictions.jsonl').write_text(json.dumps({'instance_id':task['instance_id'],
        'model_name_or_path':'keel-saved-snapshot','model_patch':patch})+'\n',encoding='utf-8')
    (export/'export-receipt.json').write_text(json.dumps({'instance_id':task['instance_id'],
        'runtime_status':'saved_snapshot_only','predictions_sha256':file_hash(export/'predictions.jsonl'),
        'task_receipt_sha256':file_hash(task_dir/'task-receipt.json')}),encoding='utf-8')
    report={'status':'grading','source_files':hashes,'patch_sha256':hashlib.sha256(patch.encode()).hexdigest(),
        'model_calls':0,'benchmark_ready':False,'reference_grade_sha256':file_hash(reference_dir/'grading.json'),
        'scope':'Independent grading of saved workspace, not resumed Agent execution, runtime pass, or a replacement first-attempt score'}
    try:
        kwargs={'environment_overlay':overlay} if overlay is not None else {}
        result=grade(task_dir,export,output/'grading',python=python,timeout=timeout,**policies,**kwargs)
        if any(file_hash(repo/name)!=value for name,value in hashes.items()):
            raise ValueError('Saved workspace changed during grading')
        report.update(status=result['status'],official_resolved=result['official_resolved'],grading=result)
    finally:
        (output/'snapshot-grade.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'export', 'reference', 'grade','recover-reference','grade-snapshot'))
    parser.add_argument('--reference-grade',type=Path)
    parser.add_argument('--failed-grade',type=Path)
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--instance-id')
    parser.add_argument('--task', type=Path)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--export', dest='export_dir', type=Path)
    parser.add_argument('--model-name', default='keel')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--network-policy', choices=['no_pipeline'])
    parser.add_argument('--timeout', type=int, default=1800,
                        help='Total grading deadline in seconds, including image builds (default: 1800)')
    args = parser.parse_args()
    if args.action == 'prepare':
        if not args.dataset or not args.instance_id:
            parser.error('prepare requires dataset and instance-id')
        result = prepare(args.dataset, args.instance_id, args.output)
    elif args.action == 'export':
        if not args.task or not args.run:
            parser.error('export requires task and run')
        result = export_prediction(args.task, args.run, args.output, args.model_name)
    elif args.action == 'reference':
        if not args.task:
            parser.error('reference requires task')
        result = reference_prediction(args.task, args.output)
    elif args.action=='grade-snapshot':
        if not args.task or not args.run or not args.reference_grade:
            parser.error('grade-snapshot requires task, run (saved repo), reference-grade')
        if not args.execute:
            result={'status':'plan_only','next':'Grade saved source without restarting Agent inference'}
        else:
            result=grade_snapshot(args.task.resolve(),args.run.resolve(),args.reference_grade.resolve(),
                                  args.output.resolve(),python=sys.executable,timeout=args.timeout)
    elif args.action=='recover-reference':
        if not args.task or not args.export_dir or not args.failed_grade:
            parser.error('recover-reference requires task, export and failed-grade')
        if not args.execute:
            result={'status':'plan_only','next':'Inspect collision, isolated removal and independent reference grading'}
        else:
            from keel.reference_recovery import recover_reference
            result=recover_reference(args.task.resolve(),args.export_dir.resolve(),args.failed_grade.resolve(),
                args.output.resolve(),python=sys.executable,timeout=args.timeout,grader=grade)
    else:
        if not args.task or not args.export_dir:
            parser.error('grade requires task and export')
        if not args.execute:
            result = {'status': 'plan_only', 'next': 'Invoke official Docker harness with --execute', 'benchmark_ready': False}
        else:
            result = grade(args.task.resolve(), args.export_dir.resolve(), args.output.resolve(), timeout=args.timeout, network_policy=args.network_policy)
    print(json.dumps(result, indent=2))
    return 1 if result.get('status') in ('grading_error','environment_unresolved') else 0


if __name__ == '__main__':
    raise SystemExit(main())
