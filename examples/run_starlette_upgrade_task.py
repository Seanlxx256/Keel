"""Prepare or run one exploratory real compatibility task; gold stays curator-only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import check_snapshot
from keel.execution import CommandRunner
from keel.runtime import run
from examples.reproduce_starlette_1936 import BASE, GOLD, PROBE, assess

GOAL = (
    'Make Starlette TestClient compatible with AnyIO 4.0.0 while preserving its existing behavior. '
    'A plain HTTP request and entering TestClient as a context manager currently fail with '
    "AttributeError: module 'anyio' has no attribute 'start_blocking_portal'. "
    'Inspect starlette/testclient.py and implement the compatibility fix in that file only. '
    'Do not change dependencies, tests, or other files. Use repository tools to inspect code '
    'and apply real edits; independent Docker acceptance will check both execution paths.'
)


def inventory(root):
    result = {}
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if '.git' in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError('Symlinks are not allowed in this task export')
        if path.is_file():
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def verify_range(base, gold):
    check_snapshot(base, BASE)
    check_snapshot(gold, GOLD)
    commit = subprocess.run(['git', '-c', f'safe.directory={gold.as_posix()}', '-C', str(gold),
        'cat-file', '-p', GOLD], check=True, capture_output=True, text=True, timeout=15).stdout
    parents = [line.split()[1] for line in commit.split('\n\n', 1)[0].splitlines() if line.startswith('parent ')]
    if not parents or parents[0] != BASE:
        raise ValueError('Gold first parent does not match pinned base')
    before, after = inventory(base), inventory(gold)
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    if changed != ['starlette/testclient.py']:
        raise ValueError('Snapshot changes differ from archived PR file list')
    return {'first_parent_verified': True, 'changed_files': changed,
            'base_inventory': before, 'gold_inventory': after}


def task_config(image, *, model='keel-chat', num_ctx=4096, max_seconds=900):
    return {'mode': 'agent', 'context_handoff': True, 'goal': GOAL,
        'model': {'provider': 'ollama', 'name': model, 'base_url': 'http://localhost:11434',
                  'num_gpu': 0, 'num_ctx': num_ctx},
        'agent': {'max_steps': 12, 'max_output': 1024, 'require_evidence': True, 'max_work_items': 1,
                  'max_context_bytes': 12000},
        'budget': {'max_wallclock': max_seconds, 'max_model_calls': 30,
                   'max_tool_calls': 60, 'max_tokens': 180000},
        'execution': {'backend': 'docker', 'image': image},
        'acceptance': [['python', '-c', PROBE]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reproduction', required=True, type=Path, help='Successful reproduction artifact directory')
    parser.add_argument('--execute', action='store_true', help='Run the real CPU Ollama agent and Docker verification')
    parser.add_argument('--max-seconds', type=int, default=900, help='Agent runtime budget; baseline is separate')
    parser.add_argument('--max-steps', type=int, default=12, help='Maximum model turns per role')
    parser.add_argument('--model', default='keel-chat', help='Existing Ollama model name; no automatic downloads')
    parser.add_argument('--max-context-bytes', type=int, default=12000, help='Message plus schema byte cap, not exact tokens')
    parser.add_argument('--unbounded-context', action='store_true', help='Disable history compaction for controlled comparison')
    args = parser.parse_args()
    if args.max_seconds <= 0 or not 2 <= args.max_steps <= 30 or args.max_context_bytes <= 0:
        parser.error('--max-seconds must be positive and --max-steps must be 2..30')
    root = Path(__file__).resolve().parents[1]
    output = root / '.keel/upgradebench-agent' / uuid.uuid4().hex
    output.mkdir(parents=True)
    print(f'Artifacts: {output}', flush=True)
    summary = {'prepared': False, 'executed': False, 'task_passed': False, 'benchmark_ready': False,
               'limitations': 'One exploratory task, two acceptance cases; host agent, Docker verifier only. No benchmark resolve rate.'}
    stop = threading.Event()
    thread = None
    try:
        evidence_path = args.reproduction / 'summary.json'
        evidence_bytes = evidence_path.read_bytes()
        evidence = json.loads(evidence_bytes)
        if evidence.get('candidate') != 'kludex__starlette-1936' or not assess(evidence['executions']):
            raise ValueError('Successful matching base/gold evidence is required')
        if evidence.get('probe_sha256') != hashlib.sha256(PROBE.encode()).hexdigest():
            raise ValueError('Acceptance probe differs from reproduced version')
        image = evidence['image_id']
        if not image.startswith('sha256:') or len(image) != 71:
            raise ValueError('Expected a resolved Docker image ID')
        snapshots = root / '.keel/upgradebench-snapshots/kludex--starlette'
        base, gold = snapshots / BASE, snapshots / GOLD
        verified = verify_range(base, gold)
        repo = output / 'repo'
        shutil.copytree(base, repo, ignore=shutil.ignore_patterns('.git'))
        if inventory(repo) != verified['base_inventory']:
            raise ValueError('Export differs from verified base')
        config = task_config(image, model=args.model, max_seconds=args.max_seconds)
        config['agent']['max_steps'] = args.max_steps
        if args.unbounded_context:
            config['agent'].pop('max_context_bytes')
        else:
            config['agent']['max_context_bytes'] = args.max_context_bytes
        summary['context_policy'] = {'max_input_bytes': config['agent'].get('max_context_bytes'),
                                    'output_token_limit': config['agent']['max_output'],
                                    'exact_token_counting': False}
        (output / 'task.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
        (output / 'curator.json').write_text(json.dumps({**verified, 'base': BASE, 'gold': GOLD,
            'reproduction_sha256': hashlib.sha256(evidence_bytes).hexdigest()}, indent=2), encoding='utf-8')
        summary['prepared'] = True
        if args.execute:
            docker_dir = Path('D:/Docker/Desktop/resources/bin')
            if not shutil.which('docker') and (docker_dir / 'docker.exe').is_file():
                os.environ['PATH'] = str(docker_dir) + os.pathsep + os.environ.get('PATH', '')
            runner = CommandRunner(config['execution'])
            baseline = runner.run(['python', '-c', PROBE], repo, 90)
            (output / 'baseline.json').write_text(json.dumps(baseline, indent=2), encoding='utf-8')
            if not assess({'base': baseline, 'gold': evidence['executions']['gold']}):
                raise ValueError('Current baseline no longer matches reproduced API failure')
            started = time.monotonic()
            def heartbeat():
                while not stop.wait(10):
                    print(f'[Keel +{time.monotonic()-started:.0f}s] agent running; trace: {output / "run/trace.jsonl"}', flush=True)
            thread = threading.Thread(target=heartbeat, daemon=True)
            thread.start()
            summary['executed'] = True
            result = run(config, repo, output / 'run')
            final = inventory(repo)
            changed = sorted(path for path in verified['base_inventory'].keys() | final.keys()
                if verified['base_inventory'].get(path) != final.get(path))
            summary.update(runtime_status=result['status'], failure=result['failure'],
                changed_files=changed, model_calls=result['budget']['model_calls'])
            final_runs = result.get('verification', [])
            summary['task_passed'] = (result['status'] == 'passed' and changed == ['starlette/testclient.py']
                and result['budget']['model_calls'] > 0 and len(final_runs) == 1
                and assess({'base': baseline, 'gold': final_runs[0]}))
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        summary['error'] = str(error)
    finally:
        stop.set()
        if thread:
            thread.join(timeout=1)
        (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if summary['task_passed'] or (summary['prepared'] and not args.execute) else 1


if __name__ == '__main__':
    raise SystemExit(main())
