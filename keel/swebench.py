"""Local SWE-bench artifact boundary; official harness owns final grading."""
import json
from pathlib import Path
import re
import subprocess

from .evaluation_protocol import file_hash


def solver_task(row):
    fields = ('instance_id', 'repo', 'base_commit', 'problem_statement')
    if any(not isinstance(row.get(key), str) or not row[key].strip() for key in fields):
        raise ValueError('Instance requires ID, repo, base commit and problem statement')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\d+', row['instance_id']):
        raise ValueError('Invalid SWE-bench instance ID')
    if not re.fullmatch(r'[0-9a-f]{40}', row['base_commit']):
        raise ValueError('Full base commit required')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', row['repo']):
        raise ValueError('Invalid repository')
    if any(part in {'.', '..'} for part in row['repo'].split('/')) or not row['instance_id'].lower().startswith(row['repo'].replace('/', '__').lower()+'-'):
        raise ValueError('Repository and instance ID differ')
    # Explicit whitelist: patch/test_patch/F2P/P2P/hints never enter the goal.
    return {key: row[key] for key in fields}


def prepare(dataset, instance_id, output):
    raw = dataset.read_text(encoding='utf-8')
    rows = json.loads(raw) if dataset.suffix == '.json' else [json.loads(line) for line in raw.splitlines() if line.strip()]
    matches = [row for row in rows if row.get('instance_id') == instance_id]
    if len(matches) != 1:
        raise ValueError('Require exactly one matching dataset instance')
    row = matches[0]
    task = solver_task(row)
    if not isinstance(row.get('patch'), str) or not isinstance(row.get('test_patch'), str):
        raise ValueError('Full local benchmark record required for private grading')
    output.mkdir(parents=True, exist_ok=False)
    (output/'solver-task.json').write_text(json.dumps(task, indent=2), encoding='utf-8')
    # Keep this file OUTSIDE any solver workspace. It includes reference answers.
    (output/'grader-dataset.jsonl').write_text(json.dumps(row)+'\n', encoding='utf-8')
    receipt = {'instance_id': instance_id, 'dataset_sha256': file_hash(dataset),
               'solver_task_sha256': file_hash(output/'solver-task.json'),
               'grader_dataset_sha256': file_hash(output/'grader-dataset.jsonl'),
               'benchmark_ready': False, 'scope': 'Local frozen record; no unseen-task or execution claim'}
    (output/'task-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


def verify_task(task_dir):
    receipt = json.loads((task_dir/'task-receipt.json').read_text(encoding='utf-8'))
    if (file_hash(task_dir/'solver-task.json') != receipt['solver_task_sha256'] or
            file_hash(task_dir/'grader-dataset.jsonl') != receipt['grader_dataset_sha256']):
        raise ValueError('Task changed after preparation')
    task = solver_task(json.loads((task_dir/'solver-task.json').read_text(encoding='utf-8')))
    if task['instance_id'] != receipt['instance_id']:
        raise ValueError('Task identity mismatch')
    return task


def export_prediction(task_dir, run_dir, output, model_name, *, source_repo=None):
    task = verify_task(task_dir)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}', model_name):
        raise ValueError('Simple model label required, not a path or credential')
    result = json.loads((run_dir/'result.json').read_text(encoding='utf-8'))
    if result.get('goal') != task['problem_statement']:
        raise ValueError('Run goal must match the frozen issue exactly')
    if result.get('status') not in {'passed', 'failed'}:
        raise ValueError('Terminal runtime result required')
    patch = (run_dir/'changes.patch').read_text(encoding='utf-8')
    if source_repo is not None:
        patch=workspace_patch(source_repo,task)
    output.mkdir(parents=True, exist_ok=False)
    prediction = {'instance_id': task['instance_id'], 'model_name_or_path': model_name, 'model_patch': patch}
    (output/'predictions.jsonl').write_text(json.dumps(prediction)+'\n', encoding='utf-8')
    receipt = {'instance_id': task['instance_id'], 'runtime_status': result['status'],
               'runtime_failure': result.get('failure'), 'empty_patch': not patch.strip(),
               'patch_sha256': file_hash(run_dir/'changes.patch'), 'result_sha256': file_hash(run_dir/'result.json'),
               'predictions_sha256': file_hash(output/'predictions.jsonl'),
               'task_receipt_sha256': file_hash(task_dir/'task-receipt.json'),
               'official_resolved': None, 'benchmark_ready': False,
               'scope': 'Operator-associated run; goal match does not prove source provenance. Official grading pending.'}
    if source_repo is not None:
        receipt['patch_scope']='Full base-relative Git diff including validated seed changes; runtime changes.patch remains the new-attempt delta'
    (output/'export-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


def grading_outcome(report, identity):
    if not isinstance(report, dict) or identity not in report:
        raise ValueError('Official report missing requested instance')
    row = report[identity]
    if not isinstance(row, dict) or type(row.get('resolved')) is not bool:
        raise ValueError('Official resolved must be boolean')
    if row['resolved'] and row.get('patch_successfully_applied') is not True:
        raise ValueError('Resolved report lacks patch application evidence')
    return {'official_resolved': row['resolved'], 'patch_successfully_applied': row.get('patch_successfully_applied'),
            'infra_failure': row.get('infra_failure'), 'benchmark_ready': False}


def validate_harness_schema(row, version):
    if version and int(version.split('.')[0]) >= 5:
        missing = sorted({'image', 'eval_script', 'log_parser', 'eval_type'} - row.keys())
        if missing:
            raise ValueError('Harness '+version+' requires new task-schema fields: '+', '.join(missing)+
                             '. This classic Verified export targets swebench==3.0.0; use an isolated pinned environment.')


def reference_prediction(task_dir, output):
    """Curator-only environment preflight; never an agent prediction."""
    task = verify_task(task_dir)
    row = json.loads((task_dir/'grader-dataset.jsonl').read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=False)
    prediction = {'instance_id': task['instance_id'], 'model_name_or_path': 'reference-preflight', 'model_patch': row['patch']}
    (output/'predictions.jsonl').write_text(json.dumps(prediction)+'\n', encoding='utf-8')
    receipt = {'instance_id': task['instance_id'], 'runtime_status': 'reference_only',
               'predictions_sha256': file_hash(output/'predictions.jsonl'),
               'task_receipt_sha256': file_hash(task_dir/'task-receipt.json'),
               'scope': 'Gold environment preflight, zero agent runs; never include in agent scores'}
    (output/'export-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


def workspace_patch(repo, task):
    def git(*args):
        result = subprocess.run(['git', '-c', 'safe.directory='+repo.resolve().as_posix(), '-c', 'core.autocrlf=false',
                                 '-C', str(repo), *args], check=True, capture_output=True, timeout=30)
        return result.stdout.decode('utf-8')
    if git('rev-parse', 'HEAD').strip() != task['base_commit']:
        raise ValueError('Solver HEAD differs from frozen base commit')
    return git('diff', '--no-ext-diff', '--no-textconv', '--binary', 'HEAD', '--')
