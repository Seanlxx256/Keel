"""New historical issue-range probe retaining the unchanged five-case acceptance."""
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

from examples.reproduce_flask_login_813 import COMMON, TARGETS, CASES, PROBE, assess, diagnose
from examples.mine_upgradebench import GitHub, replay_fetch, unique_file_paths


BASE = 'abab0cbf5fd3f172a26e710b5326790d5703f334'
GOLD = 'e95b034ed173b0fcdcaee48b3b82f68e70053e50'


def selected_candidate(root, history):
    from examples.trace_import_fix import trace
    saved = json.loads((history/'result.json').read_text(encoding='utf-8'))
    verified = trace(replay_fetch(history), 'maxcountryman/flask-login',
        'e6424a62b3dbdfd789ce6775678c262fa31cbefc', 'src/flask_login/utils.py', 'werkzeug.urls', 'url_decode')
    if saved != verified or saved.get('base_commit') != BASE or saved.get('gold_commit') != '7b170bf4e5e0240fe084166c9ca6ec4fba258dcd':
        raise ValueError('Matching hash-verified historical import removal required')
    return {'repository': 'maxcountryman/flask-login', 'base_commit': BASE, 'gold_commit': GOLD,
            'range_kind': 'historical issue range, not adjacent PR first-parent pair',
            'intermediate_import_removal': saved['gold_commit'],
            'reason': 'Preserve existing five-case acceptance; early import removal alone lacks blank-query preservation'}


def verify_comparison(comparison):
    if (comparison.get('status') != 'ahead' or comparison.get('base_commit', {}).get('sha') != BASE or
            comparison.get('merge_base_commit', {}).get('sha') != BASE or
            type(comparison.get('total_commits')) is not int or not 1 <= comparison['total_commits'] <= 20):
        raise ValueError('Bounded ancestor-to-descendant comparison required')
    rows = comparison.get('files')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 300:
        raise ValueError('Bounded comparison file list required')
    files, operations = unique_file_paths(rows, len({r['filename'] for r in rows}))
    return {'files': sorted(files), 'file_operations': operations, 'total_commits': comparison['total_commits']}


def verify_sources(row, before, after):
    check_snapshot(before, BASE)
    check_snapshot(after, GOLD)
    left, right = inventory(before), inventory(after)
    changed = sorted(n for n in left.keys() | right.keys() if left.get(n) != right.get(n))
    if changed != row['comparison']['files']:
        raise ValueError('Actual pinned range differs from archived ancestor comparison')
    return {'changed_files_curator_only': changed, 'base_inventory': left, 'gold_inventory': right,
            'ancestry_rule': 'GitHub compare status ahead and merge-base equals fixed base; exact file delta',
            'comparison': row['comparison']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', required=True, type=Path)
    parser.add_argument('--build-images', action='store_true')
    parser.add_argument('--offline', action='store_true', help='Snapshots offline only; ancestry comparison still requires GitHub')
    args = parser.parse_args()
    if args.offline and args.build_images:
        parser.error('--offline cannot build images')
    root = Path(__file__).resolve().parents[1]
    row = selected_candidate(root, args.history)
    output = root/'.keel/upgradebench-reproduction'/uuid.uuid4().hex
    output.mkdir(parents=True)
    print(f'Artifacts: {output}', flush=True)
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
    report = {'candidate': 'maxcountryman__flask-login-issue5279-range', 'selected_metadata': row,
        'history_sha256': file_hash(args.history/'result.json'),
        'probe_passed': False, 'benchmark_ready': False, 'executions': {}, 'images': {},
        'probe_sha256': hashlib.sha256(PROBE.encode()).hexdigest(),
        'runner_sha256': file_hash(Path(__file__).resolve()), 'dependency_versions': TARGETS,
        'limitations': 'Five curated import, URL, cookie and local session cases; not full upstream suite, production authentication/security validation or agent evaluation. Only Werkzeug version varies; historical environment is reconstructed.'}
    def save():
        (output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    try:
        api = GitHub(output/'range-responses')
        comparison = api.get(f'/repos/maxcountryman/flask-login/compare/{BASE}...{GOLD}')
        row['comparison'] = verify_comparison(comparison)
        report['comparison_receipts_sha256'] = file_hash(output/'receipts.json')
        save()
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
