"""Frozen diagnostic suite: two synthetic controls and one real compatibility task."""
import argparse
import hashlib
import json
import os
import re
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
from keel.models import from_config
from examples.run_starlette_upgrade_task import inventory, verify_range, task_config
from examples.reproduce_starlette_1936 import BASE, GOLD, PROBE, assess


def controls():
    code = 'API_VERSION = 1\n\ndef greeting(name):\n    return "Hello, " + name\n'
    return [{'id': identity, 'group': 'synthetic_control', 'goal':
        'Inspect app.py. Upgrade API_VERSION to 2, preserve greeting(name), and modify only app.py.',
        'files': {'app.py': (prefix + code).encode()}, 'target': 'app.py',
        'acceptance': 'import app; assert app.API_VERSION == 2; assert app.greeting("Keel") == "Hello, Keel"'}
        for identity, prefix in [('short-version', ''), ('long-version', '# unchanged padding\n'*400)]]


def real_task(root, reproduction, case='1936'):
    if case == 'flask-wtf-565':
        from examples import reproduce_flask_wtf_565 as candidate
        raw = (reproduction/'summary.json').read_bytes()
        evidence = json.loads(raw)
        if evidence.get('candidate') != 'pallets-eco__flask-wtf-565' or not candidate.assess(evidence.get('executions')):
            raise ValueError('Matching successful Flask-WTF reproduction required')
        if evidence.get('probe_sha256') != hashlib.sha256(candidate.PROBE.encode()).hexdigest():
            raise ValueError('Reproduction probe mismatch')
        base_revision, gold_revision = evidence['base_commit'], evidence['gold_commit']
        image = evidence['image_id']
        if any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value)
               for value in (base_revision, gold_revision)) or not re.fullmatch('sha256:[0-9a-f]{64}', image):
            raise ValueError('Pinned revisions and resolved Docker image ID required')
        snapshots = root/'.keel/upgradebench-snapshots/pallets-eco--flask-wtf'
        base, gold = snapshots/base_revision, snapshots/gold_revision
        verified = candidate.verify(base_revision, gold_revision, base, gold)
        targets = ['src/flask_wtf/recaptcha/widgets.py', 'src/flask_wtf/recaptcha/validators.py']
        goal = ('Make Flask-WTF compatible with Flask 3.0.0 and Werkzeug 3.0.0. Importing flask_wtf '
            "currently raises ImportError: cannot import name 'Markup' from 'flask'. Preserve reCAPTCHA "
            'widget rendering, query parameter encoding and form rendering. Inspect and modify only '
            + ', '.join(targets) + '. Do not modify tests, dependencies or other files.')
        return {'id': 'flask-wtf-565', 'group': 'real_compatibility', 'goal': goal, 'targets': targets,
            'files': {name: (base/name).read_bytes() for name in verified['base_inventory']},
            'acceptance': candidate.PROBE, 'reference_execution': evidence['executions']['gold'],
            'assessor': candidate.assess,
            'queries': ['from flask import', 'from werkzeug.urls import', 'def recaptcha_html', 'def _validate_recaptcha']}, image, hashlib.sha256(raw).hexdigest()
    if case == '2526':
        from examples import reproduce_starlette_2526 as candidate
        raw = (reproduction/'summary.json').read_bytes()
        evidence = json.loads(raw)
        if evidence.get('candidate') != 'kludex__starlette-2526' or not candidate.assess(evidence['executions']):
            raise ValueError('Matching successful 2526 reproduction required')
        if evidence.get('probe_sha256') != hashlib.sha256(candidate.PROBE.encode()).hexdigest():
            raise ValueError('Reproduction probe mismatch')
        image = evidence['image_id']
        if len(image) != 71 or not image.startswith('sha256:'):
            raise ValueError('Resolved Docker image ID required')
        snapshots = root/'.keel/upgradebench-snapshots/kludex--starlette'
        base, gold = snapshots/candidate.BASE, snapshots/candidate.GOLD
        files = candidate.verify_range(base, gold)
        return {'id': 'starlette-2526', 'group': 'real_compatibility', 'goal': candidate.GOAL,
            'target': 'starlette/testclient.py', 'files': {name: (base/name).read_bytes() for name in files},
            'acceptance': candidate.PROBE, 'reference_execution': evidence['executions']['gold'],
            'assessor': candidate.assess, 'queries': ['class TestClient(', 'super().__init__(']}, image, hashlib.sha256(raw).hexdigest()
    if case != '1936':
        raise ValueError('Unknown real compatibility case')
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


def validate_remote_config(config):
    if not isinstance(config, dict) or config.get('provider') != 'openai-compatible':
        raise ValueError('--model-config requires an openai-compatible model object')
    from_config(config)  # Validates fields without reading keys or making requests.
    return config


def target_paths(task):
    return task['targets'] if 'targets' in task else [task['target']]


def changed_scope_passes(task, changed):
    return bool(changed) and set(changed) <= set(target_paths(task))


def prepare(output, specs, image, model, *, context_bytes=12000, strategy='tool-loop', dependency_evidence=False, model_config=None):
    from keel.evaluation_protocol import development_status
    project = Path(__file__).resolve().parents[1]
    split = {spec['id']: development_status(project, spec['id']) if spec['group'] == 'real_compatibility'
             else {'split': 'development', 'heldout_eligible': False, 'reason': 'Synthetic diagnostic control'}
             for spec in specs}
    if dependency_evidence and strategy != 'proposal':
        raise ValueError('Dependency evidence is currently available only for proposal strategy')
    if dependency_evidence and any(spec['group'] == 'real_compatibility' and spec['id'] != 'starlette-1936' for spec in specs):
        raise ValueError('Dependency evidence currently supports only starlette-1936')
    if model_config is not None:
        validate_remote_config(model_config)
        model = model_config['name']
    output.mkdir(parents=True, exist_ok=False)
    tasks = []
    for spec in specs:
        config = task_config(image, model=model, max_seconds=450)
        if model_config is not None:
            config['model'] = dict(model_config)
        config['agent']['max_steps'] = 5
        if context_bytes is None:
            config['agent'].pop('max_context_bytes')
        else:
            config['agent']['max_context_bytes'] = context_bytes
        config.update(goal=spec['goal'], acceptance=[['python', '-c', spec['acceptance']]])
        if strategy == 'proposal':
            config['mode'] = 'proposal'
            config['proposal'] = {'files': target_paths(spec),
                'queries': spec.get('queries', ['start_blocking_portal'] if spec['group'] == 'real_compatibility' else ['API_VERSION'])}
            if dependency_evidence and spec['group'] == 'real_compatibility':
                config['proposal']['dependencies'] = [{'distribution': 'anyio', 'version': '4.0.0',
                                                       'symbols': ['start_blocking_portal']}]
        preflight = None
        if strategy == 'proposal':
            from keel.proposals import source_evidence, proposal_request
            scope = config['proposal']
            evidence = [source_evidence(name, spec['files'][name].decode('utf-8'), scope['queries'])
                        for name in scope['files']]
            _, _, size = proposal_request(config['goal'], scope['files'], evidence, config['agent'])
            preflight = {'source_input_bytes': size, 'limit_bytes': config['agent'].get('max_context_bytes'),
                'dependency_evidence_included': False, 'scope': 'Source messages plus output schema; runtime rechecks including optional dependency evidence'}
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
            'targets': target_paths(spec)}
        task['evaluation'] = split[spec['id']]
        if 'target' in spec:
            task['target'] = spec['target']
        if preflight is not None:
            task['context_preflight'] = preflight
        (directory/'task.json').write_text(json.dumps(task, indent=2), encoding='utf-8')
        tasks.append(task)
    implementation = {path: hashlib.sha256((Path(__file__).resolve().parents[1]/path).read_bytes()).hexdigest()
        for path in ['keel/agents.py', 'keel/gateway.py', 'keel/conversation.py', 'keel/runtime.py',
                     'keel/models.py', 'keel/proposals.py', 'keel/workspace.py', 'keel/execution.py',
                     'keel/audit.py', 'keel/core.py', 'keel/dependency_evidence.py', 'examples/run_agent_baseline.py',
                     'examples/run_starlette_upgrade_task.py', 'examples/reproduce_starlette_1936.py',
                     'examples/reproduce_starlette_2526.py', 'examples/reproduce_flask_wtf_565.py',
                     'examples/repair_feedback.py', 'keel/evaluation_protocol.py',
                     'examples/evaluation_development_registry.json']}
    manifest = {'schema_version': 1, 'suite': 'agent-diagnostic-v1', 'model': model, 'strategy': strategy,
        'dependency_evidence_requested': dependency_evidence, 'tasks': tasks, 'evaluation_split': 'development',
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
        'response_metadata': [event['response_metadata'] for event in events
            if event['event'] == 'llm_call_finished' and event.get('response_metadata')],
        'tool_or_protocol_errors': sum(event['event'] == 'tool_or_protocol_error' for event in events),
        'failed_gateway_calls': sum(event['event'] == 'gateway_call_finished' and event.get('status') == 'failed' for event in events),
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
    parser.add_argument('--case', choices=['1936', '2526', 'flask-wtf-565'], default='1936', help='Curated real task; requires its matching reproduction')
    parser.add_argument('--model', default='keel-chat')
    parser.add_argument('--model-config', type=Path, help='Credential-free compatible model JSON; keys are environment references')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--feedback-from', type=Path, help='One explicit proposal follow-up from a saved verification failure; fresh base and budget')
    parser.add_argument('--unbounded-context', action='store_true')
    parser.add_argument('--strategy', choices=['tool-loop', 'proposal'], default='tool-loop')
    parser.add_argument('--group', choices=['synthetic_control', 'real_compatibility'], help='Run only the selected diagnostic group')
    parser.add_argument('--dependency-evidence', action='store_true', help='Retrieve static target API definitions from the fixed Docker image')
    args = parser.parse_args()
    if args.dependency_evidence and args.strategy != 'proposal':
        parser.error('--dependency-evidence requires --strategy proposal')
    if args.dependency_evidence and args.case != '1936':
        parser.error('--dependency-evidence currently supports only --case 1936')
    if args.feedback_from and (args.strategy != 'proposal' or args.group != 'real_compatibility' or args.dependency_evidence or not args.model_config):
        parser.error('--feedback-from requires proposal, real_compatibility, --model-config and no dependency evidence')
    remote = None
    if args.model_config:
        raw = args.model_config.read_bytes()
        if len(raw) > 64000:
            parser.error('Model config exceeds 64 KB')
        remote = validate_remote_config(json.loads(raw))
        args.model = remote['name']
    root = Path(__file__).resolve().parents[1]
    output = root/'.keel/agent-baseline'/uuid.uuid4().hex
    print(f'Artifacts: {output}', flush=True)
    real, image, provenance = real_task(root, args.reproduction, args.case)
    specs = controls() + [real]
    if args.group:
        specs = [spec for spec in specs if spec['group'] == args.group]
    feedback = None
    if args.feedback_from:
        from examples.repair_feedback import with_feedback
        specs[0], feedback = with_feedback(specs[0], image, args.feedback_from, remote)
    manifest = prepare(output, specs, image, args.model,
                       context_bytes=None if args.unbounded_context else 12000, strategy=args.strategy,
                       dependency_evidence=args.dependency_evidence, model_config=remote)
    if feedback:
        manifest['feedback_from'] = feedback
        (output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    records = [{'id': task['id'], 'group': task['group'], 'status': 'prepared',
                'executed': False, 'passed': False} for task in manifest['tasks']]
    report = {'prepared_only': not args.execute, 'strategy': args.strategy,
              'evaluation_split': 'development', 'heldout_eligible': False,
              'dependency_evidence_requested': args.dependency_evidence, 'records': records, 'reproduction_sha256': provenance,
              'benchmark_ready': False}
    if feedback:
        report['feedback_from'] = feedback
    def checkpoint():
        report['groups'] = summarize(records)
        (output/'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    checkpoint()
    if args.execute:
        docker_dir = Path('D:/Docker/Desktop/resources/bin')
        if not shutil.which('docker') and (docker_dir/'docker.exe').is_file():
            os.environ['PATH'] = str(docker_dir) + os.pathsep + os.environ.get('PATH', '')
        try:
            if remote:
                from_config(remote).check_credentials()
                report['model_identity'] = {'provider': 'openai-compatible', 'requested_model': remote['name'],
                    'base_url': remote['base_url'], 'identity_verified': False,
                    'scope': 'Configured endpoint/name only; response model/fingerprint recorded in trace, no weight digest claim.'}
            else:
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
                assessor = spec.get('assessor', assess)
                valid_base = (assessor({'base': baseline, 'gold': spec['reference_execution']})
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
                    accepted = accepted and assessor({'base': baseline, 'gold': verification[0]})
                record.update(status='completed', passed=result['status'] == 'passed' and accepted
                    and changed_scope_passes(task, changed) and result['budget']['model_calls'] > 0,
                    changed_files=changed, failure=result['failure'], budget=result['budget'])
                record['trace_metrics'] = trace_metrics(directory/'run/trace.jsonl')
                if not remote and model_identity(args.model) != report['model_identity']:
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
