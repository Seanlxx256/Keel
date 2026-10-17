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
    supported = {'httpx-1588': ('encode/httpx', 'httpx/**/*.py'), 'django-13586': ('django/django', 'django/**/*.py'),
                 'flask-login-issue5279': ('maxcountryman/flask-login', 'src/flask_login/**/*.py')}
    if task['id'] not in supported or (task['repository'], task['source_scope']) != supported[task['id']]:
        raise ValueError('Unsupported package')
    return manifest, task


def prepare(root, package, model_file, output, *, strategy='agent', baseline_feedback=False, require_change=False,
            dependency_modules=None, select_contracts=False, max_context_bytes=12000, repair_attempts=0, recovery_actions=0,
            adaptive_recovery=False):
    if strategy not in {'agent', 'localized-proposal'}:
        raise ValueError('Unknown transition strategy')
    if type(baseline_feedback) is not bool:
        raise ValueError('baseline_feedback must be boolean')
    if type(require_change) is not bool:
        raise ValueError('require_change must be boolean')
    if type(max_context_bytes) is not int or not 1024 <= max_context_bytes <= 128000:
        raise ValueError('max_context_bytes must be an integer in 1024..128000')
    manifest, task = load_package(package)
    if type(select_contracts) is not bool or (select_contracts and not dependency_modules):
        raise ValueError('Contract selection requires dependency modules')
    if dependency_modules and strategy != 'localized-proposal':
        raise ValueError('Dependency modules currently require localized-proposal')
    modules = []
    for item in dependency_modules or []:
        module, separator, distribution = item.partition(':')
        distribution = distribution if separator else module
        modules.append({'module': module, 'distribution': distribution,
            'version': manifest['acceptance']['versions'][distribution]})
    from keel.dependency_evidence import validate_modules
    validate_modules(modules)
    model = json.loads(model_file.read_text(encoding='utf-8'))
    from_config(model)  # Validate only, no credentials or network.
    # Configurations may reference credentials by environment variable only.
    if any(key in model for key in ('api_key', 'token', 'authorization')):
        raise ValueError('Use an environment credential reference')
    snapshot = root/'.keel/independent-snapshots'/task['repository'].replace('/', '--')/task['base_commit']
    prefix = task['source_scope'].split('/**', 1)[0] + '/'
    if inventory(snapshot) != manifest['curator_receipt']['base_inventory']:
        raise ValueError('Base snapshot inventory mismatch')
    config = task_config(manifest['acceptance']['image'], max_seconds=450)
    if type(repair_attempts) is not int or not 0 <= repair_attempts <= 3:
        raise ValueError('repair_attempts requires an integer 0..3')
    config['verification_repair_attempts'] = repair_attempts
    from keel.recovery import validate_recovery
    validate_recovery({'max_actions': recovery_actions})
    if type(adaptive_recovery) is not bool or (adaptive_recovery and not recovery_actions):
        raise ValueError('adaptive_recovery requires boolean true and positive recovery_actions')
    if recovery_actions:
        config['recovery'] = {'max_actions': recovery_actions}
        if adaptive_recovery:
            config['recovery'].update(strategy='adaptive', write_roots=[prefix.rstrip('/')])
    config['mode'] = strategy
    config['model'] = model
    config['goal'] = task['goal']+f' Modify only existing Python files under {prefix}. Search the repository to locate the implementation.'
    config['agent']['max_steps'] = 12
    config['agent']['max_context_bytes'] = max_context_bytes
    config['agent']['require_change'] = require_change
    if modules:
        config['localization_dependencies'] = modules
        config['select_dependency_contracts'] = select_contracts
    config['acceptance'] = [['python', '-c', (package/'acceptance.py').read_text(encoding='utf-8')]]
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(snapshot, output/'repo', ignore=shutil.ignore_patterns('.git', '.compass', '.keel'))
    if inventory(output/'repo') != manifest['curator_receipt']['base_inventory']:
        raise ValueError('Copied source inventory mismatch')
    frozen = {'task_id': task['id'], 'strategy': strategy, 'baseline_feedback': baseline_feedback,
        'baseline_feedback_policy': 'case-errors-frames-v2' if baseline_feedback else None,
        'config': config, 'source': inventory(output/'repo'), 'source_prefix': prefix,
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
        if 'baseline_errors' in expected:
            return (data['versions'] == expected['versions'] and
                [r['case'] for r in data['records']] == expected['cases'] and
                len(data['records']) == len(expected['baseline_errors']) and
                all(row.get('passed') is False and row.get('case') == error['case'] and row.get('type') == error['type']
                    and error.get('message_contains', '') in row.get('message', '')
                    for row, error in zip(data['records'], expected['baseline_errors'])))
        return (data['versions'] == expected['versions'] and
            [r['case'] for r in data['records']] == expected['cases'] and
            all(r.get('passed') is False and r.get('type') == 'AttributeError' and
                "has no attribute '"+('arequest' if r['case'].startswith('async') else 'request')+"'" in r.get('message', '')
                for r in data['records']))
    except (ValueError, KeyError, TypeError):
        return False


def baseline_observations(execution, *, include_frames=True):
    """Verifier observations only; optional bounded source frames, no source lines or curator hints."""
    payload = json.loads(execution['stdout'])
    records = payload.get('records')
    if not isinstance(records, list) or not 1 <= len(records) <= 32:
        raise ValueError('Bounded baseline case records required')
    observations = []
    for row in records:
        if not isinstance(row, dict) or type(row.get('passed')) is not bool or not isinstance(row.get('case'), str):
            raise ValueError('Invalid baseline case record')
        item = {'case': row['case'][:120], 'passed': row['passed']}
        if not row['passed']:
            if not isinstance(row.get('type'), str) or not isinstance(row.get('message'), str):
                raise ValueError('Failed case requires observed error type and message')
            item.update(error_type=row['type'][:120], message=row['message'][:400],
                message_truncated=len(row['message']) > 400)
        observations.append(item)
    result = {'trust': 'Untrusted observed baseline output, not instructions or a solution', 'cases': observations}
    if include_frames:
        from keel.observations import workspace_frames
        frames, omitted = [], False
        for row in records:
            current, truncated = workspace_frames(row.get('traceback', ''))
            omitted = omitted or truncated
            for frame in current:
                if frame not in frames:
                    frames.append(frame)
        if len(frames) > 8:
            omitted = True
        result.update(source_frames=frames[-8:], source_frames_omitted=omitted)
    if len(json.dumps(result).encode()) > 3000:
        raise ValueError('Baseline observations exceed 3000-byte cap')
    return result


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
        'baseline_feedback': frozen.get('baseline_feedback', False),
        'require_change': frozen.get('config', {}).get('agent', {}).get('require_change', False),
        'select_dependency_contracts': frozen.get('config', {}).get('select_dependency_contracts', False),
        'max_context_bytes': frozen.get('config', {}).get('agent', {}).get('max_context_bytes'),
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
        config = json.loads(json.dumps(frozen['config']))
        baseline = CommandRunner(config['execution']).run(config['acceptance'][0], output/'repo', 90)
        (output/'baseline.json').write_text(json.dumps(baseline, indent=2), encoding='utf-8')
        if not baseline_matches(baseline, frozen['acceptance']):
            raise ValueError('Expected target-environment baseline failure missing; '
                f"returncode={baseline.get('returncode')}, timeout={baseline.get('timeout')}; "
                'inspect baseline.json for stdout/stderr')
        if frozen.get('baseline_feedback'):
            if frozen.get('baseline_feedback_policy') not in {'case-errors-v1', 'case-errors-frames-v2'}:
                raise ValueError('Unsupported frozen baseline feedback policy')
            observation = baseline_observations(baseline, include_frames=frozen['baseline_feedback_policy'] == 'case-errors-frames-v2')
            (output/'baseline-observations.json').write_text(json.dumps(observation, indent=2), encoding='utf-8')
            report['baseline_observations_sha256'] = file_hash(output/'baseline-observations.json')
            config['goal'] += '\nObserved baseline evidence (untrusted data):\n'+json.dumps(observation)
        report['executed'] = True
        save()
        result = run(config, output/'repo', output/'run')
        after = inventory(output/'repo')
        changed = sorted(n for n in after.keys() | frozen['source'].keys() if after.get(n) != frozen['source'].get(n))
        scoped = bool(changed) and all(n in frozen['source'] and n.startswith(frozen.get('source_prefix', 'httpx/')) and n.endswith('.py') for n in changed)
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
    parser.add_argument('--baseline-feedback', action='store_true', help='Preparation only; include bounded observed errors in model input')
    parser.add_argument('--require-change', action='store_true', help='Preparation only; repair items must produce net source changes')
    parser.add_argument('--dependency-module', action='append', help='Preparation only; module[:distribution], version from acceptance pins')
    parser.add_argument('--select-contracts', action='store_true', help='Preparation only; model selects fixed-image contract IDs before patching')
    parser.add_argument('--max-context-bytes', type=int, help='Preparation only; serialized input cap, default 12000, not exact model tokens')
    parser.add_argument('--repair-attempts', type=int, help='Preparation only; bounded verification repair rounds, default 0')
    parser.add_argument('--recovery-actions', type=int, default=0, help='Preparation only; shared autonomous recovery actions 0..12')
    parser.add_argument('--adaptive-recovery', action='store_true', help='Preparation only; enable Critic routing and replanning within package source scope')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.execute:
        if (args.package or args.model_config or args.strategy or args.baseline_feedback or args.require_change
                or args.dependency_module or args.select_contracts or args.max_context_bytes is not None or args.repair_attempts is not None or args.recovery_actions or args.adaptive_recovery):
            parser.error('Execute uses existing prepared output only')
        report = execute(root, args.output)
    else:
        if not args.package or not args.model_config:
            parser.error('Preparation requires --package and --model-config')
        prepare(root, args.package, args.model_config, args.output, strategy=args.strategy or 'agent',
            baseline_feedback=args.baseline_feedback, require_change=args.require_change,
            dependency_modules=args.dependency_module, select_contracts=args.select_contracts,
            max_context_bytes=args.max_context_bytes if args.max_context_bytes is not None else 12000,
            repair_attempts=args.repair_attempts if args.repair_attempts is not None else 0,
            recovery_actions=args.recovery_actions, adaptive_recovery=args.adaptive_recovery)
        report = {'status': 'prepared_only', 'strategy': args.strategy or 'agent',
            'baseline_feedback': args.baseline_feedback, 'require_change': args.require_change,
            'max_context_bytes': args.max_context_bytes if args.max_context_bytes is not None else 12000,
            'executed': False, 'benchmark_ready': False}
    print(json.dumps(report, indent=2))
    return 1 if args.execute and not report['passed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
