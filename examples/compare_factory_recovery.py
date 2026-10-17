"""Freeze and execute repeated recovery-off/on trials on generic factory tasks.

This compares the full recovery policy, including pre-verification corrections,
not just retries after pytest failure. No independent/held-out claim is inferred.
"""
import argparse
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.run_factory_task import execute as trial, load_factory
from keel.core import digest
from keel.evaluation_protocol import file_hash, implementation_hashes
from keel.task_factory import inventory


def receipt(directory):
    load_factory(directory)
    return {'factory': file_hash(directory/'factory.json'),
            'base': inventory(directory/'base'), 'gold': inventory(directory/'gold')}


def prepare(root, output, factories, model_file, repeats=3, seed=42, cap=24000):
    if type(repeats) is not int or not 1 <= repeats <= 10 or not 4000 <= cap <= 128000:
        raise ValueError('repeats 1..10 and context cap 4000..128000 required')
    directories = [path.resolve() for path in factories]
    if not directories or len(set(directories)) != len(directories):
        raise ValueError('Unique nonempty factory list required')
    if any(output.resolve().is_relative_to(directory) for directory in directories):
        raise ValueError('Comparison output must be outside every factory directory')
    tasks, identities = [], set()
    for index, directory in enumerate(directories):
        data = load_factory(directory)
        # Different directories containing the same task do not add coverage.
        identity = digest({'candidate': data['candidate'], 'base': inventory(directory/'base')})
        if identity in identities:
            raise ValueError('Duplicate task identity')
        identities.add(identity)
        tasks.append({'id': index, 'directory': str(directory), 'receipt': receipt(directory)})
    rows = [{'task': task['id'], 'repeat': repeat, 'repair_attempts': arm,
             'directory': f"runs/task-{task['id']}-repeat-{repeat}-recovery-{arm}"}
            for task in tasks for repeat in range(1, repeats+1) for arm in (0, 3)]
    random.Random(seed).shuffle(rows)
    plan = {'tasks': tasks, 'rows': rows, 'repeats': repeats, 'seed': seed,
            'max_context_bytes': cap, 'model_file': str(model_file.resolve()),
            'model_config_sha256': file_hash(model_file), 'implementation': implementation_hashes(root),
            'benchmark_ready': False, 'heldout_tasks': 0,
            'scope': 'Full recovery policy comparison; task exposure unverified; no causal or significance claim.'}
    output.mkdir(parents=True, exist_ok=False)
    (output/'plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    (output/'plan.sha256').write_text(file_hash(output/'plan.json'), encoding='ascii')
    return plan


def summarize(rows, planned):
    arms = {}
    for arm in (0, 3):
        records = [row for row in rows if row['repair_attempts'] == arm]
        expected = sum(row['repair_attempts'] == arm for row in planned)
        completed = sum(row.get('status') == 'completed' for row in records)
        passed = sum(row.get('passed') is True for row in records)
        arms[str(arm)] = {'planned': expected, 'recorded': len(records), 'completed': completed,
                         'passed': passed, 'errors': sum(row.get('status') == 'error' for row in records),
                         'observed_pass_rate': passed/len(records) if records else None,
                         'final_pass_rate': passed/expected if expected and len(records) == expected else None}
        arms[str(arm)]['recorded_solver_cost'] = {key: sum(row.get('budget', {}).get(key, 0) for row in records)
                                               for key in ('tokens', 'model_calls', 'tool_calls', 'wallclock_seconds')}
    pairs = []
    for task, repeat in sorted({(row['task'], row['repeat']) for row in planned}):
        pair = {row['repair_attempts']: row for row in rows if row['task'] == task and row['repeat'] == repeat}
        if len(pair) == 2:
            pairs.append({'task': task, 'repeat': repeat,
                          'off_passed': pair[0].get('passed') is True, 'on_passed': pair[3].get('passed') is True,
                          'statuses': {str(arm): row['status'] for arm, row in pair.items()}})
    return {'arms': arms, 'pairs': pairs, 'unique_tasks': len({row['task'] for row in planned}),
            'planned_runs': len(planned), 'recorded_runs': len(rows), 'benchmark_ready': False}


def execute(root, output):
    if file_hash(output/'plan.json') != (output/'plan.sha256').read_text().strip():
        raise ValueError('Plan changed after freeze')
    plan = json.loads((output/'plan.json').read_text(encoding='utf-8'))
    def check():
        if implementation_hashes(root) != plan['implementation']:
            raise ValueError('Implementation changed after freeze')
        if file_hash(Path(plan['model_file'])) != plan['model_config_sha256']:
            raise ValueError('Model configuration changed after freeze')
        if any(receipt(Path(task['directory'])) != task['receipt'] for task in plan['tasks']):
            raise ValueError('Factory inputs changed after freeze')
    check()
    # Exclusive execution: a second invocation cannot overwrite prior trials.
    with (output/'execution-started.json').open('x', encoding='utf-8') as stream:
        json.dump({'started': True}, stream)
    config = json.loads(Path(plan['model_file']).read_text(encoding='utf-8'))
    tasks = {task['id']: task for task in plan['tasks']}
    report = {'status': 'running', 'records': [], 'benchmark_ready': False, 'scope': plan['scope']}
    def save():
        report['summary'] = summarize(report['records'], plan['rows'])
        (output/'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    try:
        for row in plan['rows']:
            check()
            print(f"[Recovery comparison] task={row['task']} repeat={row['repeat']} recovery={row['repair_attempts']}", flush=True)
            record = dict(row, passed=False)
            report['records'].append(record)
            try:
                result = trial(Path(tasks[row['task']]['directory']), output/row['directory'], config,
                               plan['max_context_bytes'], repair_attempts=row['repair_attempts'], check_frozen=check)
                record.update(result)
            except Exception as error:
                record.update(status='error', error=f'{type(error).__name__}: {error}')
            finally:
                save()
            check()
        report['status'] = 'completed'
    except Exception as error:
        report.update(status='stopped', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--factory', action='append', type=Path)
    parser.add_argument('--model-config', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--max-context-bytes', type=int, default=24000)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.execute:
        if args.factory or args.model_config:
            parser.error('Execute accepts the frozen output only')
        # Same Docker CLI fallback as the single-task runner.
        import os, shutil
        docker = Path('D:/Docker/Desktop/resources/bin')
        if not shutil.which('docker') and (docker/'docker.exe').is_file():
            os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
        result = execute(root, args.output.resolve())
        print(json.dumps(result, indent=2))
    else:
        if not args.factory or not args.model_config:
            parser.error('Preparation requires factories and model config')
        plan = prepare(root, args.output.resolve(), args.factory, args.model_config,
                       args.repeats, args.seed, args.max_context_bytes)
        print(json.dumps({'status': 'prepared', 'tasks': len(plan['tasks']), 'runs': len(plan['rows']),
                          'benchmark_ready': False}, indent=2))


if __name__ == '__main__':
    main()
