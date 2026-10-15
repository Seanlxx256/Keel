"""Curator-only cross-repository compatibility reproduction; no model calls."""
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
from keel.execution import CommandRunner
from examples.mine_upgradebench import GitHub
from examples.reproduce_starlette_1936 import command
from examples.run_starlette_upgrade_task import inventory

REPOSITORY = 'pallets-eco/flask-wtf'
PACKAGES = ['Flask==3.0.0', 'Werkzeug==3.0.0', 'Jinja2==3.1.2', 'MarkupSafe==2.1.3',
    'itsdangerous==2.1.2', 'click==8.1.7', 'blinker==1.6.2', 'WTForms==3.0.1']
CHANGED = ['docs/changes.rst', 'src/flask_wtf/recaptcha/validators.py',
           'src/flask_wtf/recaptcha/widgets.py', 'tests/test_recaptcha.py']
CASES = ['import', 'widget', 'query_params', 'form']
PROBE = r'''
import importlib.metadata, json, pathlib, sys, traceback
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
sys.path.insert(0, '/workspace/src')
records = []
for case in ['import', 'widget', 'query_params', 'form']:
    try:
        import flask_wtf
        assert pathlib.Path(flask_wtf.__file__).resolve().is_relative_to('/workspace/src')
        from flask import Flask
        from flask_wtf import FlaskForm, RecaptchaField
        from flask_wtf.recaptcha.widgets import RecaptchaWidget
        app = Flask(__name__)
        app.config.update(SECRET_KEY='probe-only', WTF_CSRF_ENABLED=False,
                          RECAPTCHA_PUBLIC_KEY='public-probe')
        with app.test_request_context('/'):
            if case == 'widget':
                html = str(RecaptchaWidget().recaptcha_html('public-probe'))
                assert 'g-recaptcha' in html and 'public-probe' in html
            elif case == 'query_params':
                app.config['RECAPTCHA_PARAMETERS'] = {'hl': 'zh CN', 'render': 'explicit'}
                html = unescape(str(RecaptchaWidget().recaptcha_html('public-probe')))
                class Scripts(HTMLParser):
                    sources = None
                    def handle_starttag(self, tag, attrs):
                        if tag == 'script' and dict(attrs).get('src'):
                            self.sources.append(dict(attrs)['src'])
                parser = Scripts()
                parser.sources = []
                parser.feed(html)
                assert len(parser.sources) == 1
                script = parser.sources[0]
                query = parse_qs(urlsplit(script).query)
                assert query == {'hl': ['zh CN'], 'render': ['explicit']}
            elif case == 'form':
                class Form(FlaskForm):
                    captcha = RecaptchaField()
                assert 'g-recaptcha' in str(Form().captcha())
        records.append({'case': case, 'passed': True})
    except Exception as error:
        records.append({'case': case, 'passed': False, 'type': type(error).__name__,
                        'message': str(error), 'traceback': traceback.format_exc()})
names = ['Flask', 'Werkzeug', 'Jinja2', 'MarkupSafe', 'itsdangerous', 'click', 'blinker', 'WTForms']
print(json.dumps({'records': records, 'versions': {name: importlib.metadata.version(name) for name in names}}))
raise SystemExit(0 if all(row['passed'] for row in records) else 1)
'''


def assess(executions):
    if not isinstance(executions, dict):
        return False
    for phase in ('base', 'gold'):
        run = executions.get(phase, {})
        if run.get('backend') != 'docker' or run.get('timeout') is not False or run.get('returncode') != (1 if phase == 'base' else 0):
            return False
        try:
            data = json.loads(run['stdout'])
            if data['versions'] != dict(pin.split('==') for pin in PACKAGES):
                return False
            if [row['case'] for row in data['records']] != CASES:
                return False
            for row in data['records']:
                if phase == 'gold':
                    if row.get('passed') is not True:
                        return False
                elif (row.get('passed') is not False or row.get('type') != 'ImportError' or not (
                    "cannot import name 'Markup' from 'flask'" in row.get('message', '') or
                    "cannot import name 'url_encode' from 'werkzeug.urls'" in row.get('message', ''))):
                    return False
        except (ValueError, KeyError, TypeError):
            return False
    return True


def resolve(fetch):
    pr = fetch(f'/repos/{REPOSITORY}/pulls/565')
    gold = pr.get('merge_commit_sha')
    if pr.get('merged') is not True or not isinstance(gold, str) or not re.fullmatch('[0-9a-f]{40}', gold):
        raise ValueError('Merged PR with immutable merge revision required')
    if pr.get('base', {}).get('repo', {}).get('full_name', '').lower() != REPOSITORY:
        raise ValueError('Unexpected PR repository')
    commit = fetch(f'/repos/{REPOSITORY}/commits/{gold}')
    parents = commit.get('parents', [])
    if commit.get('sha') != gold or not parents or not re.fullmatch('[0-9a-f]{40}', parents[0].get('sha', '')):
        raise ValueError('Immutable first-parent commit required')
    return parents[0]['sha'], gold


def verify(base, gold, before, after):
    check_snapshot(before, base)
    check_snapshot(after, gold)
    raw = subprocess.run(['git', '-c', f'safe.directory={after.as_posix()}', '-C', str(after),
        'cat-file', '-p', gold], check=True, capture_output=True, text=True, timeout=15).stdout
    parents = [line.split()[1] for line in raw.split('\n\n', 1)[0].splitlines() if line.startswith('parent ')]
    if not parents or parents[0] != base:
        raise ValueError('Git first parent differs from frozen metadata')
    left, right = inventory(before), inventory(after)
    changed = sorted(name for name in left.keys() | right.keys() if left.get(name) != right.get(name))
    if changed != CHANGED:
        raise ValueError(f'Unexpected changed file inventory: {changed}')
    return {'base_inventory': left, 'gold_inventory': right, 'changed_files': changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-image', action='store_true')
    parser.add_argument('--image', default='keel-flask-wtf-565:flask3')
    parser.add_argument('--metadata', type=Path, help='Reuse frozen metadata.json from an earlier run')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    if args.offline and (args.build_image or not args.metadata):
        parser.error('--offline requires --metadata and an existing image; cannot build')
    root = Path(__file__).resolve().parents[1]
    output = root/'.keel/upgradebench-reproduction'/uuid.uuid4().hex
    output.mkdir(parents=True)
    print(f'Artifacts: {output}', flush=True)
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
    report = {'candidate': 'pallets-eco__flask-wtf-565', 'probe_passed': False,
        'benchmark_ready': False, 'executions': {}, 'packages': PACKAGES,
        'source': f'https://github.com/{REPOSITORY}/pull/565',
        'probe_sha256': hashlib.sha256(PROBE.encode()).hexdigest(),
        'dependency_target': 'Flask 3.0.0 and Werkzeug 3.0.0; upstream PR addressed 2.3 deprecations',
        'original_upstream_environment_reproduced': False,
        'limitations': 'Four curated local cases; no external reCAPTCHA service, full upstream suite or agent run.'}
    try:
        if args.metadata:
            metadata = json.loads(args.metadata.read_text(encoding='utf-8'))
            if metadata.get('repository') != REPOSITORY or metadata.get('number') != 565:
                raise ValueError('Metadata candidate mismatch')
            base, gold = metadata['base_commit'], metadata['gold_commit']
            if any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value) for value in (base, gold)):
                raise ValueError('Full frozen commit hashes required')
        else:
            base, gold = resolve(GitHub(output/'github').get)
        metadata = {'repository': REPOSITORY, 'number': 565, 'base_commit': base, 'gold_commit': gold}
        raw = json.dumps(metadata, indent=2).encode()
        (output/'metadata.json').write_bytes(raw)
        report.update(metadata, metadata_sha256=hashlib.sha256(raw).hexdigest())
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
        if not re.fullmatch('sha256:[0-9a-f]{64}', image):
            raise ValueError('Resolved image ID required')
        report['image_id'] = image
        snapshots = {}
        for phase, revision in [('base', base), ('gold', gold)]:
            print(f'[UpgradeBench] preparing {phase} {revision}', flush=True)
            snapshots[phase] = prepare_snapshot(REPOSITORY, revision,
                root/'.keel/upgradebench-snapshots/pallets-eco--flask-wtf'/revision, offline=args.offline)
        report['verified_range'] = verify(base, gold, snapshots['base'], snapshots['gold'])
        runner = CommandRunner({'backend': 'docker', 'image': image})
        for phase, revision in [('base', base), ('gold', gold)]:
            print(f'[UpgradeBench] probing {phase}', flush=True)
            report['executions'][phase] = runner.run(['python', '-c', PROBE], snapshots[phase], 90)
            check_snapshot(snapshots[phase], revision)
            (output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        report['probe_passed'] = assess(report['executions'])
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    (output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['probe_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
