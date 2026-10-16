"""Frozen paired feedback ablation on existing development reproductions."""
import argparse
import copy
import json
import os
from pathlib import Path
import random
import shutil
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.run_agent_baseline import real_task, target_paths, inventory
from examples.run_starlette_upgrade_task import task_config
from keel.core import digest
from keel.evaluation_protocol import implementation_hashes, file_hash
from keel.execution import CommandRunner
from keel.models import from_config
from keel.runtime import run
from keel.repair_reporting import summarize, markdown


def pair_key(config):
    value = copy.deepcopy(config)
    value.pop('verification_repair_attempts', None)
    return digest(value)


def case_records(execution):
    data = json.loads(execution['stdout'])
    records = data['records']
    if not isinstance(records, list) or not records or any(
            not isinstance(r, dict) or not isinstance(r.get('case'), str) or type(r.get('passed')) is not bool
            for r in records) or len({r['case'] for r in records}) != len(records):
        raise ValueError('Invalid or duplicate acceptance case records')
    return {r['case']: r['passed'] for r in records}


def prepare(root, output, model_file, cases, seed=42):
    model = json.loads(model_file.read_text())
    if any(k in model for k in ('api_key', 'token', 'authorization')):
        raise ValueError('Credential environment references only')
    from_config(model)
    specs = [(case, *real_task(root, reproduction, case)) for case, reproduction in cases]
    if not specs or len({spec['id'] for _, spec, _, _ in specs}) != len(specs):
        raise ValueError('Require unique task IDs')
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for case, spec, image, provenance in specs:
        expected = case_records(spec['reference_execution'])
        if not all(expected.values()):
            raise ValueError('Reference acceptance must pass')
        common = None
        for rounds in (0, 2):
            directory = f"runs/{spec['id']}-repair-{rounds}"
            repo = output/directory/'repo'
            repo.mkdir(parents=True)
            for name, content in spec['files'].items():
                target = (repo/name).resolve()
                if not target.is_relative_to(repo.resolve()):
                    raise ValueError('Source escapes workspace')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            config = task_config(image, max_seconds=450)
            config.update(mode='localized-proposal', model=model, goal=spec['goal'],
                acceptance=[['python', '-c', spec['acceptance']]], verification_repair_attempts=rounds)
            config['agent'].update(max_steps=12, max_context_bytes=24000, require_change=True)
            key = pair_key(config)
            if common is not None and common != key:
                raise ValueError('Paired configurations differ beyond repair count')
            common = key
            rows.append({'directory': directory, 'task_id': spec['id'], 'repair_attempts': rounds,
                'config': config, 'source': inventory(repo), 'allowed_changes': target_paths(spec),
                'expected_cases': sorted(expected), 'provenance_sha256': provenance, 'pair_sha256': key})
    random.Random(seed).shuffle(rows)
    plan = {'rows': rows, 'seed': seed, 'implementation': implementation_hashes(root),
            'unique_tasks': len(specs), 'heldout_tasks': 0, 'benchmark_ready': False,
            'scope': 'Previously observed development tasks; no significance or generalization claim'}
    (output/'plan.json').write_text(json.dumps(plan, indent=2))
    (output/'plan.sha256').write_text(file_hash(output/'plan.json'))
    return plan


def execute(root, output):
    if file_hash(output/'plan.json') != (output/'plan.sha256').read_text().strip():
        raise ValueError('Plan hash mismatch')
    plan = json.loads((output/'plan.json').read_text())
    if implementation_hashes(root) != plan['implementation']:
        raise ValueError('Implementation changed after preparation')
    for row in plan['rows']:
        directory = (output/row['directory']).resolve()
        if not directory.is_relative_to(output.resolve()) or inventory(directory/'repo') != row['source']:
            raise ValueError('Source/path mismatch before any model request')
        if (directory/'run').exists() or pair_key(row['config']) != row['pair_sha256']:
            raise ValueError('Already executed or invalid paired config')
    with (output/'execution-started.json').open('x') as stream:
        json.dump({'started': True}, stream)
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker)+os.pathsep+os.environ.get('PATH', '')
    report = {'records': [], 'unique_tasks': plan['unique_tasks'], 'heldout_tasks': 0, 'benchmark_ready': False}
    def save():
        report['summary'] = summarize(report)
        (output/'results.json').write_text(json.dumps(report, indent=2))
        (output/'results.md').write_text(markdown(report['summary']), encoding='utf-8')
    save()
    for row in plan['rows']:
        record = {k: row[k] for k in ('task_id', 'repair_attempts', 'directory')}
        record.update(status='running', passed=False, executed=False)
        report['records'].append(record)
        directory = output/row['directory']
        start = time.monotonic()
        stop = threading.Event()
        def heartbeat():
            while not stop.wait(10):
                print(f"[Comparison] {record['task_id']} repair={record['repair_attempts']}", flush=True)
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            config = row['config']
            baseline = CommandRunner(config['execution']).run(config['acceptance'][0], directory/'repo', 90)
            (directory/'baseline.json').write_text(json.dumps(baseline, indent=2))
            observed = case_records(baseline)
            if (baseline['backend'] != 'docker' or baseline['timeout'] or baseline['returncode'] != 1
                    or sorted(observed) != row['expected_cases'] or all(observed.values())):
                raise ValueError('Expected baseline case failure missing')
            record['executed'] = True
            result = run(config, directory/'repo', directory/'run')
            current = inventory(directory/'repo')
            changed = sorted(n for n in current.keys() | row['source'].keys() if current.get(n) != row['source'].get(n))
            verification = result.get('verification', [])
            accepted = len(verification) == 1 and verification[0]['returncode'] == 0 and not verification[0]['timeout']
            if accepted:
                values = case_records(verification[0])
                accepted = sorted(values) == row['expected_cases'] and all(values.values()) and verification[0]['backend'] == 'docker'
            record.update(status='completed', passed=result['status'] == 'passed' and accepted
                and bool(changed) and set(changed) <= set(row['allowed_changes']) and result['budget']['model_calls'] > 0,
                changed_files=changed, failure=result['failure'], budget=result['budget'],
                verification_rounds=len(result.get('verification_attempts', [])))
        except Exception as error:
            record.update(status='runtime_error' if record['executed'] else 'environment_error',
                          error=f'{type(error).__name__}: {error}')
        finally:
            stop.set()
            thread.join(timeout=1)
            record['seconds_including_baseline'] = round(time.monotonic()-start, 3)
            save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-config', type=Path)
    parser.add_argument('--case', action='append', help='CASE=REPRODUCTION_DIRECTORY')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.execute:
        if args.model_config or args.case:
            parser.error('Execute frozen plan only')
        report = execute(root, args.output)
    else:
        if not args.model_config or not args.case:
            parser.error('Preparation requires model config and cases')
        cases = [(v.split('=', 1)[0], Path(v.split('=', 1)[1])) for v in args.case]
        plan = prepare(root, args.output, args.model_config, cases)
        report = {'prepared_only': True, 'runs': len(plan['rows']), 'unique_tasks': plan['unique_tasks'],
                  'heldout_tasks': 0, 'new_model_calls': 0}
    print(json.dumps(report, indent=2))
    return 1 if args.execute and not all(r['passed'] for r in report['records']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
