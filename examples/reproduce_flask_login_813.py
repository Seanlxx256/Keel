"""Curator three-cell transition probe from a verified explicit issue/fix pair."""
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

COMMON = ['Flask==2.3.3', 'Jinja2==3.1.2', 'MarkupSafe==2.1.3',
          'itsdangerous==2.1.2', 'click==8.1.7', 'blinker==1.6.2']
TARGETS = {'old': '2.3.7', 'new': '3.0.0'}
CASES = ['import', 'login_query', 'next_url', 'cookie_roundtrip', 'session_flow']
PROBE = r'''
import importlib.metadata, json, pathlib, sys, traceback
from urllib.parse import parse_qs, urlsplit
sys.path.insert(0, '/workspace/src')
records = []
for case in ['import', 'login_query', 'next_url', 'cookie_roundtrip', 'session_flow']:
    try:
        import flask_login
        assert pathlib.Path(flask_login.__file__).resolve().is_relative_to('/workspace/src/flask_login')
        from flask import Flask
        from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
        from flask_login.utils import login_url, make_next_param, encode_cookie, decode_cookie
        app = Flask(__name__)
        app.secret_key = 'local-probe-only'
        app.testing = True
        if case == 'login_query':
            with app.test_request_context('/'):
                value = login_url('/login?tag=a&tag=b&empty=', next_url='http://localhost/private?x=1')
                parsed = urlsplit(value)
                assert parsed.path == '/login'
                assert parse_qs(parsed.query, keep_blank_values=True) == {'tag': ['a', 'b'], 'empty': [''], 'next': ['/private?x=1']}
        elif case == 'next_url':
            assert make_next_param('https://example.com/login', 'https://example.com/private?x=1') == '/private?x=1'
            other = 'https://other.example/private?x=1'
            assert make_next_param('https://example.com/login', other) == other
        elif case == 'cookie_roundtrip':
            with app.test_request_context('/'):
                encoded = encode_cookie('alice')
                assert decode_cookie(encoded) == 'alice'
                assert decode_cookie(encoded + 'tampered') is None
        elif case == 'session_flow':
            manager = LoginManager(app)
            manager.login_view = 'login'
            class User(UserMixin):
                id = 'alice'
            @manager.user_loader
            def load_user(identity):
                return User() if identity == 'alice' else None
            @app.route('/login')
            def login():
                login_user(User())
                return 'logged in'
            @app.route('/private')
            @login_required
            def private():
                return current_user.get_id()
            @app.route('/logout')
            def logout():
                logout_user()
                return 'logged out'
            client = app.test_client()
            assert client.get('/private').status_code == 302
            assert client.get('/login').status_code == 200
            assert client.get('/private').data == b'alice'
            assert client.get('/logout').status_code == 200
            assert client.get('/private').status_code == 302
        records.append({'case': case, 'passed': True})
    except Exception as error:
        records.append({'case': case, 'passed': False, 'type': type(error).__name__,
                        'message': str(error), 'traceback': traceback.format_exc()})
names = ['Werkzeug', 'Flask', 'Jinja2', 'MarkupSafe', 'itsdangerous', 'click', 'blinker']
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
            expected['Werkzeug'] = TARGETS[dependency]
            if payload['versions'] != expected or [r['case'] for r in payload['records']] != CASES:
                return False
            for row in payload['records']:
                if passing:
                    if row.get('passed') is not True:
                        return False
                else:
                    if row.get('passed') is not False or (row.get('type') != 'ImportError' or "cannot import name 'url_decode'" not in row.get('message', '')):
                        return False
        except (ValueError, KeyError, TypeError):
            return False
    return True


def diagnose(executions):
    """Explain rejected transitions without changing the acceptance gate."""
    if assess(executions):
        return {'category': 'verified_curated_transition'}
    failed_cases = {}
    for phase in ('base_old', 'base_new', 'gold_new'):
        run = executions.get(phase)
        if run is None:
            return {'category': 'incomplete_execution', 'missing_phase': phase}
        if run.get('timeout') is not False or run.get('backend') != 'docker':
            return {'category': 'environment_or_timeout', 'phase': phase}
        try:
            payload = json.loads(run['stdout'])
            expected = dict(pin.split('==') for pin in COMMON)
            expected['Werkzeug'] = TARGETS['old' if phase == 'base_old' else 'new']
            if payload['versions'] != expected or [r['case'] for r in payload['records']] != CASES:
                raise ValueError('Unexpected versions or cases')
            failed_cases[phase] = [(r['case'], r.get('type'), r.get('message'))
                                   for r in payload['records'] if r.get('passed') is not True]
        except (ValueError, KeyError, TypeError):
            return {'category': 'invalid_probe_output', 'phase': phase}
    if failed_cases['base_old'] and failed_cases['base_old'] == failed_cases['base_new']:
        return {'category': 'same_failure_under_old_and_new_dependency',
                'failed_cases': failed_cases, 'transition_established': False}
    if failed_cases['base_old']:
        return {'category': 'old_environment_baseline_failed', 'failed_cases': failed_cases}
    return {'category': 'expected_transition_not_established', 'failed_cases': failed_cases}


def selected_candidate(root, candidate):
    from examples.mine_upgradebench import replay_fetch
    from examples.prepare_issue_candidate import collect_pair
    report = json.loads((candidate/'candidate.json').read_text(encoding='utf-8'))
    verified = collect_pair(replay_fetch(candidate), 'maxcountryman/flask-login', 813, 'pallets/flask', 5279)
    if report != verified:
        raise ValueError('Candidate differs from hash-verified issue/PR responses')
    if (report['base_commit'] != 'e6424a62b3dbdfd789ce6775678c262fa31cbefc' or
            report['gold_commit'] != 'e95b034ed173b0fcdcaee48b3b82f68e70053e50'):
        raise ValueError('Pinned first-parent/merge pair mismatch')
    return {**report, 'curator_files': sorted(report['files_curator_only'])}


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
    advertised = set(row['curator_files'])
    if not changed or not set(changed) <= advertised:
        raise ValueError('Pinned changed files contain paths outside archived PR metadata or no change')
    unchanged = sorted(advertised - set(changed))
    if any(name not in left or name not in right or left[name] != right[name] for name in unchanged):
        raise ValueError('Advertised paths omitted from pinned diff must be present and byte-identical')
    if not any(name.startswith('src/flask_login/') and name.endswith('.py') for name in changed):
        raise ValueError('Pinned range must include a library-source change')
    return {'changed_files_curator_only': changed, 'base_inventory': left, 'gold_inventory': right,
            'pr_paths_unchanged_between_pins': unchanged,
            'file_list_rule': 'first-parent delta is subset of archived PR paths; omitted paths verified identical',
            'merge_parents': parents}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--build-images', action='store_true')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    if args.offline and args.build_images:
        parser.error('--offline cannot build images')
    root = Path(__file__).resolve().parents[1]
    row = selected_candidate(root, args.candidate)
    output = root/'.keel/upgradebench-reproduction'/uuid.uuid4().hex
    output.mkdir(parents=True)
    print(f'Artifacts: {output}', flush=True)
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
    report = {'candidate': 'maxcountryman__flask-login-813', 'selected_metadata': row,
        'candidate_sha256': file_hash(args.candidate/'candidate.json'),
        'probe_passed': False, 'benchmark_ready': False, 'executions': {}, 'images': {},
        'probe_sha256': hashlib.sha256(PROBE.encode()).hexdigest(),
        'runner_sha256': file_hash(Path(__file__).resolve()), 'dependency_versions': TARGETS,
        'limitations': 'Five curated import, URL, cookie and local session cases; not full upstream suite, production authentication/security validation or agent evaluation. Only Werkzeug version varies; historical environment is reconstructed.'}
    def save():
        (output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    try:
        snapshots = {}
        for phase in ('base', 'gold'):
            revision = row[phase+'_commit']
            print(f'[Transition] preparing {phase} {revision}', flush=True)
            snapshots[phase] = prepare_snapshot('maxcountryman/flask-login', revision,
                root/'.keel/independent-snapshots/maxcountryman--flask-login'/revision, offline=args.offline)
        report['verified_range'] = verify_sources(row, snapshots['base'], snapshots['gold'])
        from keel.import_evidence import imported_symbol
        reported_source = snapshots['base']/'src/flask_login/utils.py'
        imports = imported_symbol(reported_source.read_bytes(), 'werkzeug.urls', 'url_decode')
        report['source_preflight'] = {'reported_import_present': bool(imports), 'locations': imports}
        save()
        if not imports:
            raise ValueError('Reported url_decode import is absent at pinned base; no Docker build or probe is justified for this removed-import hypothesis')
        CommandRunner({'backend': 'docker', 'image': 'python:3.11-slim'}).check_available()
        for label, version in TARGETS.items():
            tag = 'keel-flask-login-813:werkzeug'+version.replace('.', '-')
            if args.build_images:
                build = output/('image-'+label)
                build.mkdir()
                (build/'requirements.txt').write_text('\n'.join(COMMON+['Werkzeug=='+version])+'\n', encoding='ascii')
                (build/'Dockerfile').write_text('FROM python:3.11-slim\nCOPY requirements.txt /requirements.txt\n'
                    'RUN python -m pip install --no-cache-dir --no-deps -r /requirements.txt && python -m pip check\n', encoding='ascii')
                print(f'[Transition] building {label} dependency image', flush=True)
                command(['docker', 'build', '-t', tag, str(build)], output, 'image-build-'+label, 900)
            image = json.loads(command(['docker', 'image', 'inspect', tag], output, 'image-inspect-'+label))[0]['Id']
            if not re.fullmatch('sha256:[0-9a-f]{64}', image):
                raise ValueError('Resolved Docker image ID required')
            report['images'][label] = image
            save()
        for phase, snapshot, dependency in [('base_old', 'base', 'old'), ('base_new', 'base', 'new'), ('gold_new', 'gold', 'new')]:
            print(f'[Transition] probing {phase}', flush=True)
            runner = CommandRunner({'backend': 'docker', 'image': report['images'][dependency]})
            report['executions'][phase] = runner.run(['python', '-c', PROBE], snapshots[snapshot], 90)
            check_snapshot(snapshots[snapshot], row[snapshot+'_commit'])
            save()
        report['probe_passed'] = assess(report['executions'])
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    report['diagnosis'] = diagnose(report['executions'])
    save()
    print(json.dumps({key: value for key, value in report.items() if key != 'verified_range'}, indent=2))
    return 0 if report['probe_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
