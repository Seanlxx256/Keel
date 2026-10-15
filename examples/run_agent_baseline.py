"""Frozen diagnostic suite: two synthetic controls and one real compatibility task."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.core import digest
from keel.runtime import run
from keel.execution import CommandRunner
from examples.run_starlette_upgrade_task import inventory, verify_range, task_config
from examples.reproduce_starlette_1936 import BASE, GOLD, PROBE, assess


def controls():
    code = 'API_VERSION = 1\n\ndef greeting(name):\n    return "Hello, " + name\n'
    return [{'id': identity, 'group': 'synthetic_control', 'goal':
        'Inspect app.py. Upgrade API_VERSION to 2, preserve greeting(name), and modify only app.py.',
        'files': {'app.py': (prefix + code).encode()}, 'target': 'app.py',
        'acceptance': 'import app; assert app.API_VERSION == 2; assert app.greeting("Keel") == "Hello, Keel"'}
        for identity, prefix in [('short-version', ''), ('long-version', '# unchanged padding\n'*400)]]


def real_task(root, reproduction):
    raw = (reproduction/'summary.json').read_bytes()
    evidence = json.loads(raw)
    if evidence.get('candidate') != 'kludex__starlette-1936' or not assess(evidence['executions']):
        raise ValueError('Matching successful reproduction required')
    if evidence.get('probe_sha256') != hashlib.sha256(PROBE.encode()).hexdigest():
        raise ValueError('Reproduction probe mismatch')
    snapshots = root/'.keel/upgradebench-snapshots/kludex--starlette'
    base, gold = snapshots/BASE, snapshots/GOLD
    verified = verify_range(base, gold)
    spec = {'id': 'starlette-1936', 'group': 'real_compatibility',
        'goal': task_config(evidence['image_id'])['goal'], 'target': 'starlette/testclient.py',
        'files': {path: (base/path).read_bytes() for path in verified['base_inventory']},
        'acceptance': PROBE, 'reference_execution': evidence['executions']['gold']}
    return spec, evidence['image_id'], hashlib.sha256(raw).hexdigest()


def prepare(output, specs, image, model, *, context_bytes=12000, strategy='tool-loop', dependency_evidence=False):
    if dependency_evidence and strategy != 'proposal':
        raise ValueError('Dependency evidence is currently available only for proposal strategy')
    output.mkdir(parents=True, exist_ok=False)
    tasks = []
    for spec in specs:
        config = task_config(image, model=model, max_seconds=450)
        config['agent']['max_steps'] = 5
        if context_bytes is None:
            config['agent'].pop('max_context_bytes')
        else:
            config['agent']['max_context_bytes'] = context_bytes
        config.update(goal=spec['goal'], acceptance=[['python', '-c', spec['acceptance']]])
        if strategy == 'proposal':
            config['mode'] = 'proposal'
            config['proposal'] = {'files': [spec['target']],
                'queries': ['start_blocking_portal'] if spec['group'] == 'real_compatibility' else ['API_VERSION']}
            if dependency_evidence and spec['group'] == 'real_compatibility':
                config['proposal']['dependencies'] = [{'distribution': 'anyio', 'version': '4.0.0',
                                                       'symbols': ['start_blocking_portal']}]
        directory = output/'tasks'/spec['id']
        repo = directory/'template'
        repo.mkdir(parents=True)
        for path, raw in spec['files'].items():
            target = repo/path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        files = inventory(repo)
        comparison = json.loads(json.dumps(config))
        comparison['model'].pop('name')
        task = {'id': spec['id'], 'group': spec['group'], 'config': config, 'source_sha256': files,
            'comparison_key': digest({'source': files, 'config_except_model_name': comparison}),
            'target': spec['target']}
        (directory/'task.json').write_text(json.dumps(task, indent=2), encoding='utf-8')
        tasks.append(task)
    implementation = {path: hashlib.sha256((Path(__file__).resolve().parents[1]/path).read_bytes()).hexdigest()
        for path in ['keel/agents.py', 'keel/gateway.py', 'keel/conversation.py', 'keel/runtime.py',
                     'keel/models.py', 'keel/proposals.py', 'keel/workspace.py', 'keel/execution.py',
                     'keel/audit.py', 'keel/core.py', 'keel/dependency_evidence.py', 'examples/run_agent_baseline.py']}
    manifest = {'schema_version': 1, 'suite': 'agent-diagnostic-v1', 'model': model, 'strategy': strategy,
        'dependency_evidence_requested': dependency_evidence, 'tasks': tasks,
        'implementation_sha256': implementation, 'benchmark_ready': False,
        'limitations': 'Synthetic controls and real tasks are separate groups. One real task, no benchmark resolve-rate claim.'}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def summarize(records):
    groups = {}
    for record in records:
        group = groups.setdefault(record['group'], {'planned': 0, 'executed': 0, 'passed': 0, 'environment_errors': 0})
        group['planned'] += 1
        group['executed'] += int(record.get('executed', False))
        group['passed'] += int(record.get('passed', False) and record.get('status') == 'completed')
        group['environment_errors'] += int(record.get('status') == 'environment_error')
    return groups


def trace_metrics(path):
    events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    calls = {}
    for event in events:
        if event['event'] == 'gateway_call_started':
            tool = event['tool']
            calls[tool] = calls.get(tool, 0) + 1
    return {'max_model_input_bytes': max((event['input_bytes'] for event in events
            if event['event'] == 'llm_call_started'), default=0),
        'archived_turns': sum(event['archived_turns'] for event in events if event['event'] == 'context_window'),
        'dependency_scans': sum(event['event'] == 'dependency_scan_finished' for event in events),
        'dependency_symbol_matches': sum(event['matches'] for event in events if event['event'] == 'dependency_scan_finished'),
        'tool_calls_by_name': calls}


def model_identity(name):
    with urllib.request.urlopen('http://localhost:11434/api/tags', timeout=15) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError('Model listing too large')
    wanted = name if ':' in name else name + ':latest'
    matches = [row for row in json.loads(raw)['models'] if row.get('name') == wanted]
    if len(matches) != 1 or not matches[0].get('digest'):
        raise ValueError('Requested model is not uniquely installed')
    return {'name': wanted, 'digest': matches[0]['digest']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reproduction', required=True, type=Path)
    parser.add_argument('--model', default='keel-chat')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--unbounded-context', action='store_true')
    parser.add_argument('--strategy', choices=['tool-loop', 'proposal'], default='tool-loop')
    parser.add_argument('--group', choices=['synthetic_control', 'real_compatibility'], help='Run only the selected diagnostic group')
    parser.add_argument('--dependency-evidence', action='store_true', help='Retrieve static target API definitions from the fixed Docker image')
    args = parser.parse_args()
    if args.dependency_evidence and args.strategy != 'proposal':
        parser.error('--dependency-evidence requires --strategy proposal')
    root = Path(__file__).resolve().parents[1]
    output = root/'.keel/agent-baseline'/uuid.uuid4().hex
    print(f'Artifacts: {output}', flush=True)
    real, image, provenance = real_task(root, args.reproduction)
    specs = controls() + [real]
    if args.group:
        specs = [spec for spec in specs if spec['group'] == args.group]
    manifest = prepare(output, specs, image, args.model,
                       context_bytes=None if args.unbounded_context else 12000, strategy=args.strategy,
                       dependency_evidence=args.dependency_evidence)
    records = [{'id': task['id'], 'group': task['group'], 'status': 'prepared',
                'executed': False, 'passed': False} for task in manifest['tasks']]
    report = {'prepared_only': not args.execute, 'strategy': args.strategy,
              'dependency_evidence_requested': args.dependency_evidence, 'records': records, 'reproduction_sha256': provenance,
              'benchmark_ready': False}
    def checkpoint():
        report['groups'] = summarize(records)
        (output/'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    checkpoint()
    if args.execute:
        docker_dir = Path('D:/Docker/Desktop/resources/bin')
        if not shutil.which('docker') and (docker_dir/'docker.exe').is_file():
            os.environ['PATH'] = str(docker_dir) + os.pathsep + os.environ.get('PATH', '')
        try:
            report['model_identity'] = model_identity(args.model)
        except (OSError, ValueError, KeyError) as error:
            for record in records:
                record.update(status='environment_error', error=str(error))
            checkpoint()
            print(json.dumps(report, indent=2))
            return 1
        for number, (task, spec, record) in enumerate(zip(manifest['tasks'], specs, records), 1):
            print(f'[Baseline {number}/{len(records)}] {task["id"]}', flush=True)
            directory = output/'runs'/task['id']
            repo = directory/'repo'
            shutil.copytree(output/'tasks'/task['id']/'template', repo)
            stop = threading.Event()
            started = time.monotonic()
            def heartbeat():
                while not stop.wait(10):
                    print(f'[Baseline +{time.monotonic()-started:.0f}s] {task["id"]}', flush=True)
            thread = threading.Thread(target=heartbeat, daemon=True)
            thread.start()
            try:
                if inventory(repo) != task['source_sha256']:
                    raise ValueError('Source differs from frozen manifest')
                baseline = CommandRunner(task['config']['execution']).run(task['config']['acceptance'][0], repo, 90)
                (directory/'baseline.json').write_text(json.dumps(baseline, indent=2), encoding='utf-8')
                valid_base = (assess({'base': baseline, 'gold': spec['reference_execution']})
                    if task['group'] == 'real_compatibility' else
                    baseline['returncode'] == 1 and not baseline['timeout'] and 'AssertionError' in baseline['stderr'])
                if not valid_base:
                    raise ValueError('Expected baseline failure was not reproduced')
                record.update(status='running', executed=True)
                checkpoint()
                result = run(task['config'], repo, directory/'run')
                current = inventory(repo)
                changed = sorted(path for path in current.keys() | task['source_sha256'].keys()
                    if current.get(path) != task['source_sha256'].get(path))
                verification = result.get('verification', [])
                accepted = len(verification) == 1 and verification[0]['backend'] == 'docker' and not verification[0]['timeout'] and verification[0]['returncode'] == 0
                if task['group'] == 'real_compatibility':
                    accepted = accepted and assess({'base': baseline, 'gold': verification[0]})
                record.update(status='completed', passed=result['status'] == 'passed' and accepted
                    and changed == [task['target']] and result['budget']['model_calls'] > 0,
                    changed_files=changed, failure=result['failure'], budget=result['budget'])
                record['trace_metrics'] = trace_metrics(directory/'run/trace.jsonl')
                if model_identity(args.model) != report['model_identity']:
                    record.update(status='environment_error', passed=False, error='Model identity changed during suite')
            except Exception as error:
                record.update(status='runtime_error' if record['executed'] else 'environment_error',
                              passed=False, error=f'{type(error).__name__}: {error}')
            finally:
                stop.set()
                thread.join(timeout=1)
                record['seconds_including_baseline'] = round(time.monotonic()-started, 3)
                checkpoint()
    print(json.dumps(report, indent=2))
    return 0 if not args.execute or all(record['passed'] for record in records) else 1


if __name__ == '__main__':
    raise SystemExit(main())
