"""Curator-only two-revision API compatibility probe; no agent or benchmark score."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.preparation import prepare_snapshot
from compass.benchmarks import check_snapshot
from keel.execution import CommandRunner

BASE = 'fbab16a2b114321c1694788b21113bbba8943778'
GOLD = 'a45027209ae4c033007d827a37bbbee53550973a'
# Explicit alternative target: released AnyIO 4.0.0, NOT the unreleased commit
# cited by the original PR. Success establishes only this selected environment.
PACKAGES = ['anyio==4.0.0', 'httpx==0.23.3', 'httpcore==0.16.3', 'h11==0.14.0',
            'sniffio==1.3.0', 'idna==3.4', 'certifi==2023.7.22', 'rfc3986==1.5.0']
PROBE = r'''
import importlib.metadata, json, traceback
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
async def endpoint(request):
    return JSONResponse({'ok': True})
app = Starlette(routes=[Route('/', endpoint)])
records = []
for case in ['request', 'lifespan']:
    try:
        if case == 'request':
            response = TestClient(app).get('/')
        else:
            with TestClient(app) as client:
                response = client.get('/')
        assert response.status_code == 200 and response.json() == {'ok': True}
        records.append({'case': case, 'passed': True})
    except Exception as error:
        records.append({'case': case, 'passed': False, 'type': type(error).__name__,
                        'message': str(error), 'traceback': traceback.format_exc()})
print(json.dumps({'records': records, 'versions': {name: importlib.metadata.version(name)
    for name in ['anyio', 'httpx', 'httpcore', 'h11', 'sniffio', 'idna', 'certifi', 'rfc3986']}}))
raise SystemExit(0 if all(row['passed'] for row in records) else 1)
'''


def assess(executions):
    """Require identical cases/dependencies and the specific expected base error."""
    parsed = {}
    for phase in ('base', 'gold'):
        run = executions[phase]
        if run.get('timeout') or run.get('backend') != 'docker':
            return False
        try:
            parsed[phase] = json.loads(run['stdout'])
        except (ValueError, KeyError):
            return False
        rows = parsed[phase].get('records', [])
        if [row.get('case') for row in rows] != ['request', 'lifespan']:
            return False
        expected = dict(package.split('==') for package in PACKAGES)
        if parsed[phase].get('versions') != expected:
            return False
    base, gold = parsed['base']['records'], parsed['gold']['records']
    return (executions['base']['returncode'] == 1 and executions['gold']['returncode'] == 0
        and all(row.get('passed') is False and row.get('type') == 'AttributeError'
            and "module 'anyio' has no attribute 'start_blocking_portal'" in row.get('message', '')
            for row in base)
        and all(row.get('passed') is True for row in gold))


def command(args, output, name, timeout=300):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    (output / (name + '.stdout.log')).write_bytes(result.stdout)
    (output / (name + '.stderr.log')).write_bytes(result.stderr)
    if result.returncode:
        raise ValueError(f'{name} failed; inspect its saved logs')
    return result.stdout.decode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-image', action='store_true', help='Build the pinned dependency image (requires network)')
    parser.add_argument('--offline', action='store_true', help='Require existing Git snapshots; no image build')
    parser.add_argument('--image', default='keel-starlette-1936:anyio4')
    args = parser.parse_args()
    if args.offline and args.build_image:
        parser.error('--offline cannot be combined with --build-image')
    root = Path(__file__).resolve().parents[1]
    output = root / '.keel/upgradebench-reproduction' / uuid.uuid4().hex
    output.mkdir(parents=True)
    print(f'Artifacts: {output}', flush=True)
    docker_dir = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker_dir / 'docker.exe').is_file():
        os.environ['PATH'] = str(docker_dir) + os.pathsep + os.environ.get('PATH', '')
    summary = {'candidate': 'kludex__starlette-1936', 'probe_passed': False,
               'benchmark_ready': False, 'dependency_target': 'released AnyIO 4.0.0',
               'original_upstream_commit_reproduced': False, 'executions': {},
               'probe_sha256': hashlib.sha256(PROBE.encode()).hexdigest(), 'packages': PACKAGES,
               'limitations': 'Curated two-case API probe only; no full test suite, agent run, or ready benchmark task.'}
    try:
        runner = CommandRunner({'backend': 'docker', 'image': args.image})
        runner.check_available()
        if args.build_image:
            build = output / 'image'
            build.mkdir()
            (build / 'requirements.txt').write_text('\n'.join(PACKAGES) + '\n', encoding='ascii')
            (build / 'Dockerfile').write_text(
                'FROM python:3.11-slim\nCOPY requirements.txt /requirements.txt\n'
                'RUN python -m pip install --no-cache-dir --no-deps -r /requirements.txt && python -m pip check\n', encoding='ascii')
            print('[UpgradeBench] building dependency image (network required)', flush=True)
            command(['docker', 'build', '-t', args.image, str(build)], output, 'image-build', 900)
        image_id = json.loads(command(['docker', 'image', 'inspect', args.image], output, 'image-inspect'))[0]['Id']
        summary['image_id'] = image_id
        runner = CommandRunner({'backend': 'docker', 'image': image_id})
        for phase, revision in [('base', BASE), ('gold', GOLD)]:
            print(f'[UpgradeBench] preparing {phase} {revision}', flush=True)
            snapshot = prepare_snapshot('kludex/starlette', revision,
                root / '.keel/upgradebench-snapshots/kludex--starlette' / revision, offline=args.offline)
            check_snapshot(snapshot, revision)
            print(f'[UpgradeBench] probing {phase}', flush=True)
            execution = runner.run(['python', '-c', PROBE], snapshot, 90)
            summary['executions'][phase] = execution
            check_snapshot(snapshot, revision)
            (output / (phase + '.json')).write_text(json.dumps(execution, indent=2), encoding='utf-8')
        summary['probe_passed'] = assess(summary['executions'])
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        summary['error'] = str(error)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if summary['probe_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
