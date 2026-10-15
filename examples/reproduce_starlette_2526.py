"""Curated HTTPX 0.28.1 compatibility probe; no model calls or benchmark claim."""
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
from examples.reproduce_starlette_1936 import command
from examples.run_starlette_upgrade_task import inventory

BASE = '7533b61a34f8b0dcb5fc35c717d458439f0baf18'
GOLD = 'a4cd0b5506ac2fd3fa0ce1e967f019b94df87b97'
PACKAGES = ['anyio==4.3.0', 'httpx==0.28.1', 'httpcore==1.0.7', 'h11==0.14.0',
    'sniffio==1.3.1', 'idna==3.10', 'certifi==2024.12.14', 'typing_extensions==4.12.2']
CASES = ['request', 'lifespan', 'redirect', 'cookie']
GOAL = ('Make Starlette TestClient compatible with HTTPX 0.28.1 while preserving request, '
    'lifespan, redirect and cookie behavior. TestClient construction currently fails with '
    'TypeError about an unexpected keyword argument in Client.__init__. '
    'Inspect and modify only starlette/testclient.py. Do not modify dependencies, tests or other files.')
PROBE = r'''
import importlib.metadata, json, traceback
from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route
from starlette.testclient import TestClient
async def endpoint(request):
    response = JSONResponse({'ok': True, 'cookie': request.cookies.get('probe')})
    response.set_cookie('server', 'present')
    return response
async def redirect(request):
    return RedirectResponse('/')
app = Starlette(routes=[Route('/', endpoint), Route('/redirect', redirect)])
records = []
for case in ['request', 'lifespan', 'redirect', 'cookie']:
    try:
        if case == 'lifespan':
            with TestClient(app) as client:
                response = client.get('/')
        elif case == 'redirect':
            response = TestClient(app).get('/redirect', follow_redirects=True)
            assert len(response.history) == 1
        elif case == 'cookie':
            client = TestClient(app, cookies={'probe': 'kept'})
            response = client.get('/')
            assert response.json()['cookie'] == 'kept' and client.cookies['server'] == 'present'
        else:
            response = TestClient(app).get('/')
        assert response.status_code == 200 and response.json()['ok'] is True
        records.append({'case': case, 'passed': True})
    except Exception as error:
        records.append({'case': case, 'passed': False, 'type': type(error).__name__,
                        'message': str(error), 'traceback': traceback.format_exc()})
names = ['anyio', 'httpx', 'httpcore', 'h11', 'sniffio', 'idna', 'certifi', 'typing_extensions']
print(json.dumps({'records': records, 'versions': {name: importlib.metadata.version(name) for name in names}}))
raise SystemExit(0 if all(row['passed'] for row in records) else 1)
'''


def assess(executions):
    for phase in ('base', 'gold'):
        run = executions.get(phase, {})
        if run.get('backend') != 'docker' or run.get('timeout') is not False or run.get('returncode') != (1 if phase == 'base' else 0):
            return False
        try:
            payload = json.loads(run['stdout'])
            if payload['versions'] != dict(package.split('==') for package in PACKAGES):
                return False
            rows = payload['records']
            if [row['case'] for row in rows] != CASES:
                return False
            for row in rows:
                if phase == 'gold':
                    if row.get('passed') is not True:
                        return False
                elif (row.get('passed') is not False or row.get('type') != 'TypeError'
                    or "unexpected keyword argument 'app'" not in row.get('message', '')
                    or 'Client.__init__' not in row.get('message', '')):
                    return False
        except (ValueError, KeyError, TypeError):
            return False
    return True


def verify_range(base, gold):
    check_snapshot(base, BASE)
    check_snapshot(gold, GOLD)
    raw = subprocess.run(['git', '-c', f'safe.directory={gold.as_posix()}', '-C', str(gold),
        'cat-file', '-p', GOLD], check=True, capture_output=True, text=True, timeout=15).stdout
    parents = [line.split()[1] for line in raw.split('\n\n', 1)[0].splitlines() if line.startswith('parent ')]
    if not parents or parents[0] != BASE:
        raise ValueError('Gold first parent differs from pinned base')
    before, after = inventory(base), inventory(gold)
    changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    if changed != ['starlette/testclient.py']:
        raise ValueError('Unexpected changed file inventory')
    return before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-image', action='store_true')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--image', default='keel-starlette-2526:httpx028')
    args = parser.parse_args()
    if args.offline and args.build_image:
        parser.error('--offline cannot build images')
    root = Path(__file__).resolve().parents[1]
    output = root/'.keel/upgradebench-reproduction'/uuid.uuid4().hex
    output.mkdir(parents=True)
    print(f'Artifacts: {output}', flush=True)
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
    report = {'candidate': 'kludex__starlette-2526', 'probe_passed': False, 'benchmark_ready': False,
        'base_commit': BASE, 'gold_commit': GOLD, 'packages': PACKAGES, 'executions': {},
        'probe_sha256': hashlib.sha256(PROBE.encode()).hexdigest(),
        'dependency_target': 'released HTTPX 0.28.1 (original PR addressed 0.27 deprecation)',
        'original_upstream_environment_reproduced': False,
        'source': 'https://github.com/Kludex/starlette/pull/2526',
        'limitations': 'Four curated API cases, same repository as 1936; no full suite, agent success or independent benchmark claim.'}
    try:
        CommandRunner({'backend': 'docker', 'image': args.image}).check_available()
        if args.build_image:
            build = output/'image'
            build.mkdir()
            (build/'requirements.txt').write_text('\n'.join(PACKAGES)+'\n', encoding='ascii')
            (build/'Dockerfile').write_text('FROM python:3.11-slim\nCOPY requirements.txt /requirements.txt\n'
                'RUN python -m pip install --no-cache-dir --no-deps -r /requirements.txt && python -m pip check\n', encoding='ascii')
            print('[UpgradeBench] building dependency image', flush=True)
            command(['docker', 'build', '-t', args.image, str(build)], output, 'image-build', 900)
        image = json.loads(command(['docker', 'image', 'inspect', args.image], output, 'image-inspect'))[0]['Id']
        if len(image) != 71 or not image.startswith('sha256:'):
            raise ValueError('Resolved image ID required')
        report['image_id'] = image
        snapshots = {}
        for phase, commit in [('base', BASE), ('gold', GOLD)]:
            print(f'[UpgradeBench] preparing {phase} {commit}', flush=True)
            snapshots[phase] = prepare_snapshot('kludex/starlette', commit,
                root/'.keel/upgradebench-snapshots/kludex--starlette'/commit, offline=args.offline)
        verify_range(snapshots['base'], snapshots['gold'])
        runner = CommandRunner({'backend': 'docker', 'image': image})
        for phase, commit in [('base', BASE), ('gold', GOLD)]:
            print(f'[UpgradeBench] probing {phase}', flush=True)
            report['executions'][phase] = runner.run(['python', '-c', PROBE], snapshots[phase], 90)
            check_snapshot(snapshots[phase], commit)
            (output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        report['probe_passed'] = assess(report['executions'])
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    (output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['probe_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
