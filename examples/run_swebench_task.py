"""Run adaptive Keel on frozen base source, using the official harness for verification."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.preparation import prepare_snapshot
from examples.swebench_bridge import grade
from keel.campaign_reporting import FrozenModel
from keel.evaluation_protocol import implementation_hashes, file_hash
from keel.models import from_config
from keel.runtime import run
from keel.swebench import verify_task, export_prediction


def check_reference(task_dir, reference_dir):
    verify_task(task_dir)
    result = json.loads((reference_dir/'grading.json').read_text(encoding='utf-8'))
    if (result.get('status') != 'graded' or result.get('official_resolved') is not True or
            result.get('runtime_status') != 'reference_only' or result.get('harness_version') != '3.0.0'):
        raise ValueError('Successful classic reference-only preflight required')
    expected = json.loads((task_dir/'grader-dataset.jsonl').read_text(encoding='utf-8'))
    actual = json.loads((reference_dir/'grader-input.json').read_text(encoding='utf-8'))
    if actual != [expected] or file_hash(reference_dir/'grader-input.json') != result['grader_input_sha256']:
        raise ValueError('Reference preflight belongs to different task data')


def config_for(task, task_dir, output, model_config, harness_python):
    verifier = Path(__file__).with_name('swebench_verify_workspace.py').resolve()
    return {'mode': 'localized-proposal', 'goal': task['problem_statement'], 'model': model_config,
            'agent': {'max_steps': 12, 'max_context_bytes': 48000, 'max_output': 4096, 'require_change': True},
            'recovery': {'strategy': 'adaptive', 'max_actions': 6, 'repeat_limit': 2, 'write_roots': ['.']},
            'verification_repair_attempts': 3,
            'budget': {'max_wallclock': 1800, 'max_model_calls': 30, 'max_tokens': 180000, 'max_tool_calls': 80},
            'execution': {'backend': 'local'},
            'acceptance': [[sys.executable, str(verifier), '--task', str(task_dir.resolve()),
                            '--output-root', str((output/'verifications').resolve()),
                            '--harness-python', str(Path(harness_python).resolve())]]}


def execute(root, task_dir, reference_dir, model_config, harness_python, output):
    check_reference(task_dir, reference_dir)
    task = verify_task(task_dir)
    version = subprocess.run([harness_python, '-c', 'import importlib.metadata; print(importlib.metadata.version("swebench"))'],
                             check=True, capture_output=True, text=True, timeout=20).stdout.strip()
    if version != '3.0.0':
        raise ValueError('This frozen classic-data trial requires harness 3.0.0')
    if output.resolve().is_relative_to(task_dir.resolve()):
        raise ValueError('Trial output must be outside private task directory')
    output.mkdir(parents=True, exist_ok=False)
    hashes = implementation_hashes(root)
    task_receipt = file_hash(task_dir/'task-receipt.json')
    def frozen():
        if implementation_hashes(root) != hashes or file_hash(task_dir/'task-receipt.json') != task_receipt:
            raise ValueError('Implementation or task changed during execution')
        verify_task(task_dir)
    model = FrozenModel(from_config(model_config), frozen)
    report = {'status': 'preparing', 'instance_id': task['instance_id'], 'official_resolved': None,
              'benchmark_ready': False, 'implementation': hashes,
              'scope': 'Exploratory public task; prior exposure unverified. Host agent and verifier launcher; official Docker harness executes tests.'}
    def save():
        (output/'trial.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(10):
            print(f"[Keel SWE-bench] {task['instance_id']} stage={report['status']}; artifacts={output}", flush=True)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        repo = prepare_snapshot(task['repo'], task['base_commit'], output/'repo', timeout=180)
        config = config_for(task, task_dir, output, model_config, harness_python)
        (output/'input-receipt.json').write_text(json.dumps({'task_receipt_sha256': task_receipt,
            'base_commit': task['base_commit'], 'goal': task['problem_statement']}, indent=2), encoding='utf-8')
        report['status'] = 'agent_running'
        save()
        result = run(config, repo, output/'run', model=model)
        report.update(runtime_status=result['status'], failure=result.get('failure'), budget=result['budget'],
                      recovery=result.get('recovery'), verification_rounds=len(result.get('verification_attempts', [])))
        frozen()
        export_prediction(task_dir, output/'run', output/'prediction', 'keel')
        report['status'] = 'final_grading'
        save()
        final = grade(task_dir, output/'prediction', output/'final-grade', python=harness_python)
        report.update(status='completed' if final['status'] == 'graded' else 'grading_error',
                      official_resolved=final['official_resolved'], grading_error=final.get('error'))
    except Exception as error:
        report.update(status='error', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        stop.set()
        thread.join(timeout=1)
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', required=True, type=Path)
    parser.add_argument('--reference-grade', required=True, type=Path)
    parser.add_argument('--model-config', required=True, type=Path)
    parser.add_argument('--harness-python', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    check_reference(args.task, args.reference_grade)
    if not args.execute:
        print(json.dumps({'status': 'plan_only', 'instance_id': verify_task(args.task)['instance_id'], 'max_model_calls': 30,
                          'max_agent_seconds': 1800, 'max_verification_rounds': 4, 'benchmark_ready': False}))
        return 0
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
    report = execute(Path(__file__).resolve().parents[1], args.task.resolve(), args.reference_grade.resolve(),
                     json.loads(args.model_config.read_text(encoding='utf-8')), str(args.harness_python.resolve()), args.output.resolve())
    print(json.dumps({key: value for key, value in report.items() if key != 'implementation'}, indent=2))
    return 0 if report['official_resolved'] is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
