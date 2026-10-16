"""Prepare then execute one frozen package trial; no curator localization or gold input."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.evaluation_protocol import file_hash, implementation_hashes
from keel.models import from_config
from keel.runtime import run
from keel.execution import CommandRunner
from examples.run_starlette_upgrade_task import inventory, task_config


def load_package(package):
    manifest = json.loads((package/'manifest.json').read_text(encoding='utf-8'))
    if set(manifest['files']) != {'task.json', 'acceptance.py'}:
        raise ValueError('Unexpected package file set')
    for name, expected in manifest['files'].items():
        if file_hash(package/name) != expected:
            raise ValueError('Package file hash mismatch')
    task = json.loads((package/'task.json').read_text(encoding='utf-8'))
    if task['id'] != 'httpx-1588' or task['repository'] != 'encode/httpx' or task['source_scope'] != 'httpx/**/*.py':
        raise ValueError('Unsupported package')
    return manifest, task


def prepare(root, package, model_file, output, *, strategy='agent'):
    if strategy not in {'agent', 'localized-proposal'}:
        raise ValueError('Unknown transition strategy')
    manifest, task = load_package(package)
    model = json.loads(model_file.read_text(encoding='utf-8'))
    from_config(model)  # Validate only, no credentials or network.
    # Configurations may reference credentials by environment variable only.
    if any(key in model for key in ('api_key', 'token', 'authorization')):
        raise ValueError('Use an environment credential reference')
    snapshot = root/'.keel/independent-snapshots/encode--httpx'/task['base_commit']
    if inventory(snapshot) != manifest['curator_receipt']['base_inventory']:
        raise ValueError('Base snapshot inventory mismatch')
    config = task_config(manifest['acceptance']['image'], max_seconds=450)
    config['mode'] = strategy
    config['model'] = model
    config['goal'] = task['goal']+' Modify only existing Python files under httpx/. Search the repository to locate the implementation.'
    config['agent']['max_steps'] = 12
    config['acceptance'] = [['python', '-c', (package/'acceptance.py').read_text(encoding='utf-8')]]
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(snapshot, output/'repo', ignore=shutil.ignore_patterns('.git', '.compass', '.keel'))
    if inventory(output/'repo') != manifest['curator_receipt']['base_inventory']:
        raise ValueError('Copied source inventory mismatch')
    frozen = {'task_id': task['id'], 'strategy': strategy, 'config': config, 'source': inventory(output/'repo'),
        'acceptance': manifest['acceptance'], 'package_sha256': file_hash(package/'manifest.json'),
        'implementation': implementation_hashes(root), 'attempt': 1, 'benchmark_ready': False,
        'scope': 'Single package trial, not a repository-disjoint benchmark result'}
    (output/'prepared.json').write_text(json.dumps(frozen, indent=2), encoding='utf-8')
    (output/'prepared.sha256').write_text(file_hash(output/'prepared.json'), encoding='ascii')
    return frozen


def accepted(execution, expected):
    if execution.get('backend') != 'docker' or execution.get('returncode') != 0 or execution.get('timeout') is not False:
        return False
    try:
        payload = json.loads(execution['stdout'])
        return (payload['versions'] == expected['versions'] and
            [r['case'] for r in payload['records']] == expected['cases'] and
            all(r.get('passed') is True for r in payload['records']))
    except (ValueError, KeyError, TypeError):
        return False


def baseline_matches(execution, expected):
    if execution.get('backend') != 'docker' or execution.get('returncode') != 1 or execution.get('timeout') is not False:
        return False
    try:
        data = json.loads(execution['stdout'])
        return (data['versions'] == expected['versions'] and
            [r['case'] for r in data['records']] == expected['cases'] and
            all(r.get('passed') is False and r.get('type') == 'AttributeError' and
                "has no attribute '"+('arequest' if r['case'].startswith('async') else 'request')+"'" in r.get('message', '')
                for r in data['records']))
    except (ValueError, KeyError, TypeError):
        return False


def execute(root, output):
    if file_hash(output/'prepared.json') != (output/'prepared.sha256').read_text():
        raise ValueError('Prepared manifest changed')
    frozen = json.loads((output/'prepared.json').read_text(encoding='utf-8'))
    if implementation_hashes(root) != frozen['implementation'] or inventory(output/'repo') != frozen['source']:
        raise ValueError('Implementation or source changed since preparation')
    # Exclusive creation refuses repeat execution, including interrupted attempts.
    with (output/'execution-started.json').open('x', encoding='utf-8') as stream:
        json.dump({'attempt': 1, 'started_unix': time.time()}, stream)
    report = {'task_id': frozen['task_id'], 'attempt': 1, 'executed': False, 'passed': False,
        'strategy': frozen.get('strategy', frozen.get('config', {}).get('mode', 'agent')),
        'status': 'running', 'benchmark_ready': False, 'prepared_sha256': file_hash(output/'prepared.json')}
    def save():
        (output/'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(10):
            print('[Transition] agent trial running', flush=True)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        docker = Path('D:/Docker/Desktop/resources/bin')
        if not shutil.which('docker') and (docker/'docker.exe').is_file():
            os.environ['PATH'] = str(docker)+os.pathsep+os.environ.get('PATH', '')
        config = frozen['config']
        baseline = CommandRunner(config['execution']).run(config['acceptance'][0], output/'repo', 90)
        (output/'baseline.json').write_text(json.dumps(baseline, indent=2), encoding='utf-8')
        if not baseline_matches(baseline, frozen['acceptance']):
            raise ValueError('Expected target-environment baseline failure missing; '
                f"returncode={baseline.get('returncode')}, timeout={baseline.get('timeout')}; "
                'inspect baseline.json for stdout/stderr')
        report['executed'] = True
        save()
        result = run(config, output/'repo', output/'run')
        after = inventory(output/'repo')
        changed = sorted(n for n in after.keys() | frozen['source'].keys() if after.get(n) != frozen['source'].get(n))
        scoped = bool(changed) and all(n in frozen['source'] and n.startswith('httpx/') and n.endswith('.py') for n in changed)
        verification = result.get('verification', [])
        checks = {'runtime_passed': result['status'] == 'passed', 'nonempty_scoped_diff': scoped,
            'acceptance_passed': len(verification) == 1 and accepted(verification[0], frozen['acceptance']),
            'real_model_calls': result['budget']['model_calls'] > 0}
        report.update(status='completed', changed_files=changed, failure=result['failure'], budget=result['budget'],
            checks=checks, passed=all(checks.values()))
    except Exception as error:
        report.update(status='runtime_error' if report['executed'] else 'environment_error', error=f'{type(error).__name__}: {error}')
    finally:
        stop.set()
        thread.join(timeout=1)
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--model-config', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--strategy', choices=['agent', 'localized-proposal'], help='Preparation only; default agent')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.execute:
        if args.package or args.model_config or args.strategy:
            parser.error('Execute uses existing prepared output only')
        report = execute(root, args.output)
    else:
        if not args.package or not args.model_config:
            parser.error('Preparation requires --package and --model-config')
        prepare(root, args.package, args.model_config, args.output, strategy=args.strategy or 'agent')
        report = {'status': 'prepared_only', 'strategy': args.strategy or 'agent', 'executed': False, 'benchmark_ready': False}
    print(json.dumps(report, indent=2))
    return 1 if args.execute and not report['passed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
