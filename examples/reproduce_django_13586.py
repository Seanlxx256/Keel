"""Curator three-cell dependency-transition probe from the fixed v3 shortlist."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.preparation import prepare_snapshot
from compass.benchmarks import check_snapshot
from keel.candidate_selection import shortlist
from keel.evaluation_protocol import registry, file_hash
from examples.run_starlette_upgrade_task import inventory
from examples.reproduce_starlette_1936 import command
from keel.execution import CommandRunner

COMMON = ['pytz==2020.1', 'sqlparse==0.4.1']
TARGETS = {'old': '3.2.10', 'new': '3.3.0'}
CASES = ['parallel_static_responses']
PROBE = r'''
import asyncio, importlib.metadata, json, pathlib, threading, traceback
import django
assert pathlib.Path(django.__file__).resolve().is_relative_to('/workspace/django')
from django.conf import settings
settings.configure(DEBUG=False, SECRET_KEY='local-probe', ALLOWED_HOSTS=['*'], STATIC_URL='/static/', INSTALLED_APPS=[])
django.setup()
from django.contrib.staticfiles.handlers import StaticFilesHandlerMixin
from django.http import HttpResponse
class Handler(StaticFilesHandlerMixin):
    def __init__(self):
        self.barrier = threading.Barrier(2, timeout=5)
    def serve(self, request):
        self.barrier.wait()
        return HttpResponse(request, content_type='text/plain')
async def exercise():
    handler = Handler()
    responses = await asyncio.wait_for(asyncio.gather(
        handler.get_response_async(b'one'), handler.get_response_async(b'two')), timeout=15)
    assert [r.status_code for r in responses] == [200, 200]
    assert [r.content for r in responses] == [b'one', b'two']
records = []
try:
    asyncio.run(exercise())
    records.append({'case': 'parallel_static_responses', 'passed': True})
except Exception as error:
    records.append({'case': 'parallel_static_responses', 'passed': False,
                    'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()})
names = ['asgiref', 'pytz', 'sqlparse']
print(json.dumps({'records': records, 'versions': {name: importlib.metadata.version(name) for name in names}}))
raise SystemExit(0 if all(r['passed'] for r in records) else 1)
'''


def assess(executions):
    for phase, dependency, passing in [('base_old', 'old', True), ('base_new', 'new', False), ('gold_new', 'new', True)]:
        run = executions.get(phase, {})
        if run.get('backend') != 'docker' or run.get('timeout') is not False or run.get('returncode') != (0 if passing else 1):
            return False
        try:
            payload = json.loads(run['stdout'])
            expected = dict(pin.split('==') for pin in COMMON)
            expected['asgiref'] = TARGETS[dependency]
            if payload['versions'] != expected or [r['case'] for r in payload['records']] != CASES:
                return False
            for row in payload['records']:
                if passing:
                    if row.get('passed') is not True:
                        return False
                else:
                    if row.get('passed') is not False or row.get('type') != 'BrokenBarrierError':
                        return False
        except (ValueError, KeyError, TypeError):
            return False
    return True


def selected_candidate(root, collection):
    plan = json.loads((collection/'plan.json').read_text(encoding='utf-8'))
    report = json.loads((collection/'shortlist.json').read_text(encoding='utf-8'))
    data = json.loads((collection/'collections.json').read_text(encoding='utf-8'))
    if (plan['policy']['schema_version'] != 3 or
        plan['development_registry_sha256'] != file_hash(root/'examples/evaluation_development_registry.json') or
        plan['selector_sha256'] != file_hash(root/'keel/candidate_selection.py') or
        report != shortlist(plan['policy'], registry(root), data) or report['status'] != 'shortlisted'):
        raise ValueError('Matching complete v3 shortlist required')
    rows = [r for r in report['selected'] if r['repository'] == 'django/django' and r['number'] == 13586]
    if len(rows) != 1:
        raise ValueError('Django #13586 must already be selected; no replacement candidate allowed')
    row = dict(rows[0])
    original = next(r for r in data['django/django']['candidates'] if r['number'] == 13586)
    row['curator_files'] = sorted(original['files'])
    return row


def verify_sources(row, before, after):
    check_snapshot(before, row['base_commit'])
    check_snapshot(after, row['gold_commit'])
    raw = subprocess.run(['git', '-c', f'safe.directory={after.as_posix()}', '-C', str(after),
        'cat-file', '-p', row['gold_commit']], check=True, capture_output=True, text=True, timeout=15).stdout
    parents = [line.split()[1] for line in raw.split('\n\n', 1)[0].splitlines() if line.startswith('parent ')]
    if not parents or parents[0] != row['base_commit']:
        raise ValueError('Pinned first-parent mismatch')
    left, right = inventory(before), inventory(after)
    changed = sorted(n for n in left.keys() | right.keys() if left.get(n) != right.get(n))
    if changed != row['curator_files']:
        raise ValueError('Changed files differ from archived PR metadata')
    return {'changed_files_curator_only': changed, 'base_inventory': left, 'gold_inventory': right}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', required=True, type=Path)
    parser.add_argument('--build-images', action='store_true')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    if args.offline and args.build_images:
        parser.error('--offline cannot build images')
    root = Path(__file__).resolve().parents[1]
    row = selected_candidate(root, args.collection)
    output = root/'.keel/upgradebench-reproduction'/uuid.uuid4().hex
    output.mkdir(parents=True)
    print(f'Artifacts: {output}', flush=True)
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
    report = {'candidate': 'django__django-13586', 'selected_metadata': row,
        'collection_shortlist_sha256': file_hash(args.collection/'shortlist.json'),
        'probe_passed': False, 'benchmark_ready': False, 'executions': {}, 'images': {},
        'probe_sha256': hashlib.sha256(PROBE.encode()).hexdigest(),
        'runner_sha256': file_hash(Path(__file__).resolve()), 'dependency_versions': TARGETS,
        'limitations': 'Curated scheduling-contract probe using a barrier-instrumented serve callback; not full static-file serving, database behavior, upstream suite or agent evaluation. Python 3.9 and transitive pins are a reconstruction, not proven original upstream environment.'}
    def save():
        (output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    try:
        CommandRunner({'backend': 'docker', 'image': 'python:3.9-slim'}).check_available()
        for label, version in TARGETS.items():
            tag = 'keel-django-13586:asgiref'+version.replace('.', '-')
            if args.build_images:
                build = output/('image-'+label)
                build.mkdir()
                (build/'requirements.txt').write_text('\n'.join(COMMON+['asgiref=='+version])+'\n', encoding='ascii')
                (build/'Dockerfile').write_text('FROM python:3.9-slim\nCOPY requirements.txt /requirements.txt\n'
                    'RUN python -m pip install --no-cache-dir --no-deps -r /requirements.txt && python -m pip check\n', encoding='ascii')
                print(f'[Transition] building {label} dependency image', flush=True)
                command(['docker', 'build', '-t', tag, str(build)], output, 'image-build-'+label, 900)
            image = json.loads(command(['docker', 'image', 'inspect', tag], output, 'image-inspect-'+label))[0]['Id']
            if not re.fullmatch('sha256:[0-9a-f]{64}', image):
                raise ValueError('Resolved Docker image ID required')
            report['images'][label] = image
            save()
        snapshots = {}
        for phase in ('base', 'gold'):
            revision = row[phase+'_commit']
            print(f'[Transition] preparing {phase} {revision}', flush=True)
            snapshots[phase] = prepare_snapshot('django/django', revision,
                root/'.keel/independent-snapshots/django--django'/revision, offline=args.offline)
        report['verified_range'] = verify_sources(row, snapshots['base'], snapshots['gold'])
        for phase, snapshot, dependency in [('base_old', 'base', 'old'), ('base_new', 'base', 'new'), ('gold_new', 'gold', 'new')]:
            print(f'[Transition] probing {phase}', flush=True)
            runner = CommandRunner({'backend': 'docker', 'image': report['images'][dependency]})
            report['executions'][phase] = runner.run(['python', '-c', PROBE], snapshots[snapshot], 90)
            check_snapshot(snapshots[snapshot], row[snapshot+'_commit'])
            save()
        report['probe_passed'] = assess(report['executions'])
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    save()
    print(json.dumps({key: value for key, value in report.items() if key != 'verified_range'}, indent=2))
    return 0 if report['probe_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
