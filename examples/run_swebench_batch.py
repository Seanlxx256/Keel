"""Freeze a small new-task batch, then run reference preflights and Keel serially."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.swebench_bridge import grade
from examples.run_swebench_task import execute as run_task
from keel.core import digest
from keel.evaluation_protocol import canonical_repo, file_hash, implementation_hashes, registry
from keel.swebench import prepare as prepare_task, reference_prediction, verify_task

INSTANCE = re.compile(r'\b[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\d+\b')


def seen_tasks(root, *, timeout=120):
    seen, receipts, omitted = set(), {}, []
    deadline=time.monotonic()+timeout
    skip = {'.git', 'datasets', 'repo', 'solver-repo', 'snapshot-base', 'snapshot-gold',
            'base', 'gold', 'site-packages', 'node_modules', '__pycache__', '.venv', 'venv', 'envs'}
    for area in ('docs', '.keel'):
        for directory, directories, names in os.walk(root/area):
            if time.monotonic()>deadline:
                raise TimeoutError('Exposure scan deadline exceeded; no task list frozen')
            directories[:] = [name for name in directories if name not in skip and not name.startswith('harness-')]
            for name in names:
                path = Path(directory)/name
                if path.suffix not in {'.json', '.jsonl', '.md'}:
                    continue
                if path.stat().st_size > 5_000_000:
                    omitted.append(str(path.relative_to(root)))
                    continue
                found = set(INSTANCE.findall(path.read_text(encoding='utf-8', errors='replace')))
                if found:
                    seen.update(found)
                    receipts[str(path.relative_to(root))] = file_hash(path)
    return seen, receipts, omitted


def select(rows, excluded_ids, excluded_repos, seed=42, count=3, repositories=2):
    if not 1 <= repositories <= count <= 10:
        raise ValueError('Require 1..10 tasks and repository count <= task count')
    groups, identities = {}, set()
    for row in rows:
        identity, repo = row['instance_id'], row['repo'].lower()
        if identity in identities:
            raise ValueError('Duplicate dataset instance')
        identities.add(identity)
        if identity not in excluded_ids and repo not in excluded_repos:
            groups.setdefault(repo, []).append(row)
    key = lambda value: hashlib.sha256(f'{seed}:{value}'.encode()).hexdigest()
    chosen_repos = sorted(groups, key=key)[:repositories]
    if len(chosen_repos) != repositories:
        raise ValueError('Insufficient repositories after exclusions')
    queues = {repo: sorted(groups[repo], key=lambda row: key(row['instance_id'])) for repo in chosen_repos}
    chosen = []
    while len(chosen) < count:
        progressed = False
        for repo in chosen_repos:
            if queues[repo] and len(chosen) < count:
                chosen.append(queues[repo].pop(0))
                progressed = True
        if not progressed:
            raise ValueError('Insufficient tasks in fixed selected repositories')
    return chosen


def prepare(root, dataset, model_file, harness_python, output, seed=42, count=3, repositories=2, recover_environment=False, recover_network=False,recover_compatibility=False):
    if recover_environment and (recover_network or recover_compatibility):
        raise ValueError('Packaging recovery cannot stack with transport or dependency reconciliation')
    if not 1 <= repositories <= count <= 20:
        raise ValueError('Require 1 <= repositories <= tasks <= 20')
    if dataset.suffix == '.parquet':
        import pyarrow.parquet as pq
        rows = pq.read_table(dataset).to_pylist()
    else:
        raw = dataset.read_text(encoding='utf-8')
        rows = json.loads(raw) if dataset.suffix == '.json' else [json.loads(line) for line in raw.splitlines() if line.strip()]
    seen, exposure_receipts, omitted = seen_tasks(root)
    known = registry(root)
    excluded_repos = {canonical_repo(row['repository'], known) for row in known['tasks']}
    seen.update(row['id'] for row in known['tasks'])
    chosen = select(rows, seen, excluded_repos, seed, count=count, repositories=repositories)
    output.mkdir(parents=True, exist_ok=False)
    tasks = []
    for index, row in enumerate(chosen, 1):
        directory = output/f'task-{index}'
        directory.mkdir()
        source = directory/'dataset.jsonl'
        source.write_text(json.dumps(row)+'\n', encoding='utf-8')
        prepare_task(source, row['instance_id'], directory/'task')
        reference_prediction(directory/'task', directory/'reference')
        tasks.append({'instance_id': row['instance_id'], 'repo': row['repo'], 'directory': directory.name,
                      'receipt_sha256': file_hash(directory/'task/task-receipt.json'),
                      'reference_sha256': file_hash(directory/'reference/predictions.jsonl'),
                      'reference_receipt_sha256': file_hash(directory/'reference/export-receipt.json')})
    payload = {'tasks': tasks, 'seed': seed, 'dataset_sha256': file_hash(dataset),
               'dataset_path': str(dataset.resolve()), 'model_file': str(model_file.resolve()),
               'model_sha256': file_hash(model_file), 'harness_python': str(harness_python.resolve()),
               'implementation': implementation_hashes(root), 'exposure_receipts': exposure_receipts,
               'excluded_ids': sorted(seen), 'excluded_repositories': sorted(excluded_repos),
               'exposure_scan_omissions': omitted, 'benchmark_ready': False, 'heldout_tasks': 0,
               'scope': 'Fixed exploratory new-task list; excludes IDs found in bounded local artifacts, not proof of unseen tasks. No replacement after results.',
               'limits': {'tasks': count, 'repositories': repositories, 'max_model_calls_per_task': 30, 'max_model_calls_batch': 30*count}}
    if recover_environment:
        payload['environment_recovery'] = {'attempts': 3, 'max_steps':9, 'max_model_calls_batch': 9*count,
                                           'scope': 'packaging tools only; reconstructed conditions reported separately'}
    if recover_network:
        payload['network_recovery']={'timeout_seconds':1800,'max_steps':4,'max_model_calls_batch':4*count,
            'scope':'Explicit recovery arm; original reference failures retained, reconstructed conditions separate'}
    if recover_compatibility:
        payload['compatibility_recovery']={'timeout_seconds':1800,'attempts':1,'model_calls':0,
            'scope':'Evidence-gated SCM/declared dependency reconciliation and fresh reference grading'}
    plan = {**payload, 'plan_sha256': digest(payload)}
    (output/'plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    return plan


def verify_plan(root, output):
    plan = json.loads((output/'plan.json').read_text(encoding='utf-8'))
    if digest({key: value for key, value in plan.items() if key != 'plan_sha256'}) != plan['plan_sha256']:
        raise ValueError('Frozen plan changed')
    if implementation_hashes(root) != plan['implementation'] or file_hash(Path(plan['model_file'])) != plan['model_sha256']:
        raise ValueError('Implementation or model settings changed after freeze')
    if file_hash(Path(plan['dataset_path'])) != plan['dataset_sha256']:
        raise ValueError('Dataset changed after freeze')
    for row in plan['tasks']:
        directory = output/row['directory']
        if not directory.resolve().is_relative_to(output.resolve()):
            raise ValueError('Task path escapes batch')
        verify_task(directory/'task')
        for name, expected in [('task/task-receipt.json', row['receipt_sha256']),
                               ('reference/predictions.jsonl', row['reference_sha256']),
                               ('reference/export-receipt.json', row['reference_receipt_sha256'])]:
            if file_hash(directory/name) != expected:
                raise ValueError('Frozen task/reference changed')
    return plan


def execute(root, output):
    plan = verify_plan(root, output)
    with (output/'execution-started.json').open('x', encoding='utf-8') as stream:
        json.dump({'plan_sha256': plan['plan_sha256']}, stream)
    model = json.loads(Path(plan['model_file']).read_text(encoding='utf-8'))
    report = {'status': 'running', 'plan_sha256': plan['plan_sha256'], 'benchmark_ready': False,
              'records': [{**row, 'status': 'not_started', 'agent_executed': False, 'official_resolved': None} for row in plan['tasks']]}
    def save():
        records = report['records']
        report['counts'] = {'planned': len(records), 'agent_executed': sum(row['agent_executed'] for row in records),
            'resolved': sum(row['official_resolved'] is True for row in records),
            'reference_failed_or_error': sum(row['status'] == 'reference_failed_or_error' for row in records),
            'not_started': sum(row['status'] == 'not_started' for row in records)}
        report['counts']['resolved_original_environment'] = sum(
            row['official_resolved'] is True and not row.get('environment_scope') for row in records)
        report['counts']['resolved_reconstructed_environment'] = sum(
            row['official_resolved'] is True and bool(row.get('environment_scope')) for row in records)
        (output/'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    try:
        for row in report['records']:
            verify_plan(root, output)
            directory = output/row['directory']
            row['status'] = 'reference_running'
            save()
            print(f"[Batch] reference preflight {row['instance_id']}", flush=True)
            try:
                reference = grade(directory/'task', directory/'reference', directory/'reference-grade', python=plan['harness_python'])
                reference_dir = directory/'reference-grade'
                if reference['status'] == 'grading_error' and plan.get('environment_recovery'):
                    from examples.recover_swebench_environment import recover
                    from keel.models import from_config
                    recovery = recover(directory/'task', directory/'reference', reference_dir,
                        directory/'environment-recovery', from_config(model), plan['harness_python'],
                        attempts=plan['environment_recovery']['attempts'],
                        max_steps=plan['environment_recovery'].get('max_steps',plan['environment_recovery']['attempts']))
                    row['environment_recovery'] = recovery
                    if recovery['status'] == 'reference_verified_reconstructed':
                        reference_dir = directory/'environment-recovery'/recovery['successful_grade']
                        reference = json.loads((reference_dir/'grading.json').read_text(encoding='utf-8'))
                        row['environment_scope'] = 'reconstructed packaging overlay'
                if reference['status']=='grading_error' and plan.get('network_recovery'):
                    from keel.reference_network_recovery import failure_inputs,recover_reference_network
                    from keel.models import from_config
                    from keel.campaign_reporting import FrozenModel
                    try:
                        failure_inputs(directory/'task',directory/'reference',reference_dir)
                    except ValueError as error:
                        row['network_recovery']={'status':'not_applicable','reason':str(error)}
                    else:
                        settings=plan['network_recovery']
                        recovery=recover_reference_network(directory/'task',directory/'reference',reference_dir,
                            directory/'network-recovery',FrozenModel(from_config(model),lambda:verify_plan(root,output)),
                            python=plan['harness_python'],timeout=settings['timeout_seconds'],
                            max_steps=settings['max_steps'],grader=grade)
                        row['network_recovery']=recovery
                        if recovery['status'] in ('reference_verified','reference_verified_reconstructed'):
                            reference_dir=directory/'network-recovery/reference-grade'
                            reference=recovery['grading']
                            if recovery['status']=='reference_verified_reconstructed':
                                row['environment_scope']='reconstructed APT transport policy'
                        elif plan.get('compatibility_recovery') and recovery.get('grading',{}).get('status')=='graded':
                            reference_dir=directory/'network-recovery/reference-grade'
                            reference=recovery['grading']
                if (reference.get('status')=='graded' and reference.get('official_resolved') is False
                        and plan.get('compatibility_recovery')):
                    from keel.reference_recovery import recover_reference
                    try:
                        recovery=recover_reference(directory/'task',directory/'reference',reference_dir,
                            directory/'compatibility-recovery',python=plan['harness_python'],
                            timeout=plan['compatibility_recovery']['timeout_seconds'],grader=grade)
                    except ValueError as error:
                        recovery={'status':'not_applicable','reason':str(error)}
                    row['compatibility_recovery']=recovery
                    if recovery['status']=='reference_verified_reconstructed':
                        reference_dir=directory/'compatibility-recovery/reference-grade'
                        reference=recovery['grading']
                        row['environment_scope']='reconstructed compatibility and any declared transport policies'
                row['reference_resolved'] = reference['official_resolved']
                if reference['status'] != 'graded' or reference['official_resolved'] is not True:
                    row.update(status='reference_failed_or_error', error=reference.get('error'))
                    continue
                verify_plan(root, output)
                row['status'] = 'agent_running'
                save()
                print(f"[Batch] Keel repair {row['instance_id']}", flush=True)
                trial = run_task(root, directory/'task', reference_dir, model, plan['harness_python'], directory/'trial')
                row.update(status=trial['status'], agent_executed='runtime_status' in trial,
                           official_resolved=trial['official_resolved'], runtime_status=trial.get('runtime_status'),
                           failure=trial.get('failure'), budget=trial.get('budget'), recovery=trial.get('recovery'),
                           verification_rounds=trial.get('verification_rounds'))
            except Exception as error:
                row.update(status='error', error=f'{type(error).__name__}: {error}')
                partial_result = directory/'trial/run/result.json'
                if partial_result.is_file():
                    partial = json.loads(partial_result.read_text(encoding='utf-8'))
                    row.update(agent_executed=True, runtime_status=partial.get('status'),
                               failure=partial.get('failure'), budget=partial.get('budget'))
            finally:
                save()
            verify_plan(root, output)
        report['status'] = 'completed'
    except BaseException as error:
        report.update(status='stopped', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--model-config', type=Path)
    parser.add_argument('--harness-python', type=Path)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--tasks', type=int, default=None)
    parser.add_argument('--repositories', type=int, default=None)
    parser.add_argument('--recover-environment', action='store_true')
    parser.add_argument('--recover-network', action='store_true')
    parser.add_argument('--recover-compatibility',action='store_true')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.execute:
        if args.dataset or args.model_config or args.harness_python or args.tasks is not None or args.repositories is not None or args.recover_environment or args.recover_network or args.recover_compatibility:
            parser.error('Execute frozen output only')
        docker = Path('D:/Docker/Desktop/resources/bin')
        if not shutil.which('docker') and (docker/'docker.exe').is_file():
            os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
        report = execute(root, args.output.resolve())
        print(json.dumps(report, indent=2))
    else:
        if not args.dataset or not args.model_config or not args.harness_python:
            parser.error('Preparation requires dataset, model config, harness python')
        plan = prepare(root, args.dataset.resolve(), args.model_config.resolve(), args.harness_python.resolve(), args.output.resolve(), args.seed,
                       count=args.tasks if args.tasks is not None else 3,
                       repositories=args.repositories if args.repositories is not None else 2,
                       recover_environment=args.recover_environment, recover_network=args.recover_network,recover_compatibility=args.recover_compatibility)
        print(json.dumps({'status': 'prepared_only', 'tasks': [{key: row[key] for key in ('instance_id', 'repo')} for row in plan['tasks']],
                          'limits': plan['limits'], 'benchmark_ready': False}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
