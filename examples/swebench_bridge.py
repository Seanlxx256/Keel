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


def grade(task_dir, export_dir, output, *, python=sys.executable, timeout=1800, environment_overlay=None):
    task = verify_task(task_dir)
    receipt = json.loads((export_dir/'export-receipt.json').read_text(encoding='utf-8'))
    if (receipt['predictions_sha256'] != file_hash(export_dir/'predictions.jsonl') or
            receipt['task_receipt_sha256'] != file_hash(task_dir/'task-receipt.json')):
        raise ValueError('Export inputs changed')
    output.mkdir(parents=True, exist_ok=False)
    if environment_overlay is not None:
        from keel.harness_environment import validate_overlay
        validate_overlay(environment_overlay)
        (output/'environment-overlay.json').write_text(json.dumps(environment_overlay, indent=2), encoding='utf-8')
    run_id = 'keel-'+uuid.uuid4().hex
    command = [python, '-u', str(Path(__file__).with_name('swebench_harness_entry.py').resolve()),
               '--dataset_name', str((output/'grader-input.json').resolve()),
               '--predictions_path', str((export_dir/'predictions.jsonl').resolve()),
               '--instance_ids', task['instance_id'], '--max_workers', '1', '--run_id', run_id]
    if environment_overlay is not None:
        command.extend(['--cache_level', 'instance'])
    result = {'status': 'running', 'official_resolved': None, 'runtime_status': receipt['runtime_status'],
              'command': command, 'run_id': run_id, 'benchmark_ready': False,
              'transport_adapter': 'LF-only shell/diff/patch writes on Windows; official harness via runpy'}
    if environment_overlay is not None:
        result['environment_scope'] = 'reconstructed packaging overlay; not unchanged official environment'
        result['environment_overlay_sha256'] = file_hash(output/'environment-overlay.json')
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'export', 'reference', 'grade'))
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--instance-id')
    parser.add_argument('--task', type=Path)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--export', dest='export_dir', type=Path)
    parser.add_argument('--model-name', default='keel')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
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
    else:
        if not args.task or not args.export_dir:
            parser.error('grade requires task and export')
        if not args.execute:
            result = {'status': 'plan_only', 'next': 'Invoke official Docker harness with --execute', 'benchmark_ready': False}
        else:
            result = grade(args.task.resolve(), args.export_dir.resolve(), args.output.resolve())
    print(json.dumps(result, indent=2))
    return 1 if result.get('status') == 'grading_error' else 0


if __name__ == '__main__':
    raise SystemExit(main())
