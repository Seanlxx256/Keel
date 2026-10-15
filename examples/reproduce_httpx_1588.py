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

COMMON = ['h11==0.12.0', 'anyio==3.7.1', 'sniffio==1.3.0', 'certifi==2023.7.22',
          'idna==3.4', 'rfc3986==1.5.0', 'chardet==4.0.0', 'charset-normalizer==2.0.12']
TARGETS = {'old': '0.12.3', 'new': '0.13.0'}
CASES = ['sync_get', 'async_get', 'sync_post', 'async_post']
PROBE = r'''
import asyncio, importlib.metadata, json, pathlib, threading, traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
import httpx
assert pathlib.Path(httpx.__file__).resolve().is_relative_to('/workspace/httpx')
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def respond(self, content):
        self.send_response(200)
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)
    def do_GET(self):
        self.respond(b'hello')
    def do_POST(self):
        self.respond(self.rfile.read(int(self.headers['Content-Length'])))
server = HTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
url = 'http://127.0.0.1:' + str(server.server_port) + '/'
async def async_case(post):
    async with httpx.AsyncClient(trust_env=False) as client:
        return await client.post(url, content=b'payload') if post else await client.get(url)
records = []
try:
    for case in ['sync_get', 'async_get', 'sync_post', 'async_post']:
        try:
            post = case.endswith('post')
            if case.startswith('async'):
                response = asyncio.run(async_case(post))
            else:
                with httpx.Client(trust_env=False) as client:
                    response = client.post(url, content=b'payload') if post else client.get(url)
            assert response.status_code == 200
            assert response.content == (b'payload' if post else b'hello')
            records.append({'case': case, 'passed': True})
        except Exception as error:
            records.append({'case': case, 'passed': False, 'type': type(error).__name__,
                'message': str(error), 'traceback': traceback.format_exc()})
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
names = ['httpcore', 'h11', 'anyio', 'sniffio', 'certifi', 'idna', 'rfc3986', 'chardet', 'charset-normalizer']
print(json.dumps({'records': records, 'versions': {name: importlib.metadata.version(name) for name in names}}))
raise SystemExit(0 if all(row['passed'] for row in records) else 1)
'''


def assess(executions):
    for phase, dependency, passing in [('base_old', 'old', True), ('base_new', 'new', False), ('gold_new', 'new', True)]:
        run = executions.get(phase, {})
        if run.get('backend') != 'docker' or run.get('timeout') is not False or run.get('returncode') != (0 if passing else 1):
            return False
        try:
            payload = json.loads(run['stdout'])
            expected = dict(pin.split('==') for pin in COMMON)
            expected['httpcore'] = TARGETS[dependency]
            if payload['versions'] != expected or [r['case'] for r in payload['records']] != CASES:
                return False
            for row in payload['records']:
                if passing:
                    if row.get('passed') is not True:
                        return False
                else:
                    method = 'arequest' if row['case'].startswith('async') else 'request'
                    if (row.get('passed') is not False or row.get('type') != 'AttributeError' or
                        f"has no attribute '{method}'" not in row.get('message', '')):
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
    rows = [r for r in report['selected'] if r['repository'] == 'encode/httpx' and r['number'] == 1588]
    if len(rows) != 1:
        raise ValueError('HTTPX #1588 must already be selected; no replacement candidate allowed')
    return rows[0]


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
    if changed != ['httpx/_transports/default.py', 'setup.py', 'tests/test_exceptions.py']:
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
    report = {'candidate': 'encode__httpx-1588', 'selected_metadata': row,
        'collection_shortlist_sha256': file_hash(args.collection/'shortlist.json'),
        'probe_passed': False, 'benchmark_ready': False, 'executions': {}, 'images': {},
        'probe_sha256': hashlib.sha256(PROBE.encode()).hexdigest(),
        'runner_sha256': file_hash(Path(__file__).resolve()), 'dependency_versions': TARGETS,
        'limitations': 'Curated HTTP/1 loopback GET/POST probe, not full suite or agent evaluation. No live external service, TLS, HTTP/2, proxy or timeout-behavior claim.'}
    def save():
        (output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    try:
        CommandRunner({'backend': 'docker', 'image': 'python:3.11-slim'}).check_available()
        for label, version in TARGETS.items():
            tag = 'keel-httpx-1588:core'+version.replace('.', '-')
            if args.build_images:
                build = output/('image-'+label)
                build.mkdir()
                (build/'requirements.txt').write_text('\n'.join(COMMON+['httpcore=='+version])+'\n', encoding='ascii')
                (build/'Dockerfile').write_text('FROM python:3.11-slim\nCOPY requirements.txt /requirements.txt\n'
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
            snapshots[phase] = prepare_snapshot('encode/httpx', revision,
                root/'.keel/independent-snapshots/encode--httpx'/revision, offline=args.offline)
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
