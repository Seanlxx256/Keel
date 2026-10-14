"""Probe the real Docker verifier boundary without a model or network downloads."""
import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.execution import CommandRunner


PROBE = r'''
import json, os, pathlib

def denied(path):
    try:
        pathlib.Path(path).write_text('unexpected')
    except OSError:
        return True
    return False

status = pathlib.Path('/proc/self/status').read_text()
tmp = pathlib.Path('/tmp/keel-probe')
tmp.write_text('ok')
routes = pathlib.Path('/proc/net/route').read_text().splitlines()[1:]
mounts = {line.split()[1]: line.split()[3].split(',') for line in pathlib.Path('/proc/mounts').read_text().splitlines()}
checks = {
    'unprivileged_uid': os.getuid() == 65534,
    'workspace_readable': pathlib.Path('/workspace/fixture.txt').read_text() == 'fixture',
    'workspace_readonly': denied('/workspace/fixture.txt') and 'ro' in mounts.get('/workspace', []),
    'root_readonly': denied('/etc/keel-probe') and 'ro' in mounts.get('/', []),
    'tmp_writable': tmp.read_text() == 'ok',
    'no_new_privileges': 'NoNewPrivs:\t1' in status,
    'no_effective_capabilities': 'CapEff:\t0000000000000000' in status,
    'no_nonloopback_ipv4_routes': not any(line.split()[0] != 'lo' for line in routes),
}
print(json.dumps(checks))
raise SystemExit(0 if all(checks.values()) else 1)
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='python:3.11-slim')
    args = parser.parse_args(argv)
    output = Path(__file__).resolve().parents[1] / '.keel' / 'sandbox-probes' / uuid.uuid4().hex
    repo = output / 'repo'
    repo.mkdir(parents=True, exist_ok=False)
    fixture = repo / 'fixture.txt'
    fixture.write_text('fixture', encoding='utf-8')
    print(f'Artifacts: {output}', flush=True)
    runner = CommandRunner({'backend': 'docker', 'image': args.image})
    try:
        execution = runner.run(['python', '-c', PROBE], repo.resolve(), 45)
        checks = json.loads(execution['stdout']) if execution['returncode'] == 0 else {}
        summary = {'all_passed': execution['returncode'] == 0 and bool(checks) and all(checks.values())
                   and fixture.read_text() == 'fixture', 'checks': checks, 'execution': execution,
                   'image': args.image, 'host_fixture_unchanged': fixture.read_text() == 'fixture'}
    except (OSError, RuntimeError, ValueError) as error:
        summary = {'all_passed': False, 'error': str(error), 'image': args.image}
    summary['limitations'] = 'Verifier container only; not whole-agent/MCP isolation or proof against all escape paths. No IPv6/network-exfiltration or live resource-exhaustion claim.'
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if summary['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
