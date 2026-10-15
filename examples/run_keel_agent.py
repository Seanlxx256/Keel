"""Live Ollama agent smoke test in a persistent, disposable fixture repository."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.runtime import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--orchestrator', choices=['native', 'langgraph'], default='native')
    parser.add_argument('--context-handoff', action='store_true', help='Transfer bounded fresh file-read evidence between roles')
    parser.add_argument('--num-ctx', type=int, default=8192, help='Ollama context window (1024 to 131072)')
    parser.add_argument('--cpu', action='store_true', help='Disable GPU model offload (slower)')
    parser.add_argument('--max-seconds', type=int, default=None, help='Wall-clock budget (CPU: 900s; default: 300s)')
    parser.add_argument('--model', default='keel-chat')
    parser.add_argument('--base-url', default='http://localhost:11434')
    parser.add_argument('--backend', choices=['local', 'docker'], default='local')
    parser.add_argument('--image', default='python:3.11-slim')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args(argv)
    if not 1024 <= args.num_ctx <= 131072:
        parser.error('--num-ctx must be between 1024 and 131072')
    if args.max_seconds is not None and args.max_seconds <= 0:
        parser.error('--max-seconds must be positive')
    root = args.output_dir or Path(__file__).resolve().parents[1] / '.keel' / 'agent-smoke' / uuid.uuid4().hex
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    repo = root / 'repo'
    repo.mkdir()
    (repo / 'app.py').write_text('API_VERSION = 1\n\ndef greeting(name):\n    return "Hello, " + name\n', encoding='utf-8')
    verifier = 'python' if args.backend == 'docker' else sys.executable
    config = {
        'mode': 'agent',
        'orchestrator': args.orchestrator,
        'context_handoff': args.context_handoff,
        'goal': 'Inspect app.py. Change only API_VERSION from 1 to 2 and preserve greeting(name) behavior. '
                'Use read_file to inspect source before replace; declare app.py as the work item file.',
        'model': {'provider': 'ollama', 'name': args.model, 'base_url': args.base_url, 'num_ctx': args.num_ctx, **({'num_gpu': 0} if args.cpu else {})},
        'agent': {'max_steps': 10, 'max_output': 768, 'require_evidence': True, 'max_work_items': 1},
        'budget': {'max_wallclock': args.max_seconds if args.max_seconds is not None else (900 if args.cpu else 300), 'max_model_calls': 24, 'max_tool_calls': 40, 'max_tokens': 120000},
        'execution': {'backend': args.backend, **({'image': args.image} if args.backend == 'docker' else {})},
        'acceptance': [[verifier, '-c', 'import app; assert app.API_VERSION == 2; assert app.greeting("Keel") == "Hello, Keel"']],
    }
    (root / 'task.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    stopped = threading.Event()
    started = time.monotonic()
    def heartbeat():
        while not stopped.wait(10):
            trace = root / 'run' / 'trace.jsonl'
            stage = 'starting'
            try:
                lines = trace.read_text(encoding='utf-8').splitlines()
                if lines:
                    event = json.loads(lines[-1])
                    stage = event['role'] + '/' + event['event']
            except (OSError, ValueError):
                pass
            print(f'[Keel +{time.monotonic()-started:.0f}s] {stage}', file=sys.stderr, flush=True)
    print(f'Artifacts: {root}', flush=True)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        result = run(config, repo, root / 'run')
    finally:
        stopped.set()
        thread.join(timeout=1)
    expected = 'API_VERSION = 2\n\ndef greeting(name):\n    return "Hello, " + name\n'
    checks = {
        'runtime_passed': result['status'] == 'passed',
        'exact_expected_source': (repo / 'app.py').read_text(encoding='utf-8') == expected,
        'real_model_calls': result['budget']['model_calls'] > 0,
        'verification_backend': all(v['backend'] == args.backend for v in result['verification']) and bool(result['verification']),
        'telemetry_exported': result['telemetry']['exported'],
        'declared_change_only': result.get('audit', {}).get('changed_files') == ['app.py'],
    }
    summary = {'all_passed': all(checks.values()), 'checks': checks, 'backend': args.backend,
               'model': args.model, 'cpu_requested': args.cpu, 'model_calls': result['budget']['model_calls'],
               'failure': result['failure'], 'seconds': round(time.monotonic()-started, 3),
               'source_sha256': hashlib.sha256((repo / 'app.py').read_bytes()).hexdigest(),
               'limitations': 'One synthetic task; Docker, when selected, isolates verifier commands only. Agent and MCP processes remain on host.'}
    (root / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if summary['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
