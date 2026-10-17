"""Export a bounded task package from a successful curator reproduction; no inference."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples import reproduce_flask_login_issue5279 as reproduction
from keel.evaluation_protocol import file_hash


def export(source, output):
    summary = source/'summary.json'
    report = json.loads(summary.read_text(encoding='utf-8'))
    row = report['selected_metadata']
    if (report.get('candidate') != 'maxcountryman__flask-login-issue5279-range' or
        report.get('probe_passed') is not True or not reproduction.assess(report.get('executions', {})) or
        report.get('probe_sha256') != hashlib.sha256(reproduction.PROBE.encode()).hexdigest() or
        report.get('runner_sha256') != file_hash(Path(reproduction.__file__)) or
        row.get('repository') != 'maxcountryman/flask-login' or
        row.get('base_commit') != 'abab0cbf5fd3f172a26e710b5326790d5703f334' or
        row.get('gold_commit') != 'e95b034ed173b0fcdcaee48b3b82f68e70053e50'):
        raise ValueError('Matching successful three-cell reproduction required')
    images = report.get('images', {})
    if set(images) != {'old', 'new'} or any(not re.fullmatch('sha256:[0-9a-f]{64}', str(v)) for v in images.values()):
        raise ValueError('Resolved dependency image IDs required')
    # Deliberate allowlist: no PR body, gold revision, diff or curator source paths.
    task = {'id': 'flask-login-issue5279', 'repository': 'maxcountryman/flask-login',
        'base_commit': row['base_commit'],
        'goal': 'Restore Flask-Login behavior after upgrading Werkzeug from 2.3.7 to 3.0.0 with Flask 2.3.3. Preserve package import, login redirect query parameters including repeated and empty values, same-host and external next URLs, signed cookie behavior and local login/logout sessions. Fix existing library source without changing tests, dependency versions or verification infrastructure.',
        'source_scope': 'src/flask_login/**/*.py',
        'localization': 'Repository search required; no curator file localization supplied.'}
    output.mkdir(parents=True, exist_ok=False)
    (output/'task.json').write_text(json.dumps(task, indent=2)+'\n', encoding='utf-8')
    (output/'acceptance.py').write_text(reproduction.PROBE, encoding='utf-8')
    manifest = {'schema_version': 1, 'id': task['id'],
        'files': {n: file_hash(output/n) for n in ('task.json', 'acceptance.py')},
        'acceptance': {'image': images['new'], 'timeout_seconds': 90,
            'cases': reproduction.CASES, 'versions': dict(pin.split('==') for pin in reproduction.COMMON+['Werkzeug==3.0.0']),
            'baseline_errors': [{'case': case, 'type': 'ImportError', 'message_contains': "cannot import name 'url_decode'"} for case in reproduction.CASES],
            'backend': 'docker', 'command': ['python', '-c', '<verified acceptance.py contents>']},
        'curator_receipt': {'summary_sha256': file_hash(summary),
            'history_sha256': report['history_sha256'],
            'comparison_receipts_sha256': report['comparison_receipts_sha256'],
            'base_inventory': report['verified_range']['base_inventory']},
        'model_input_files': ['task.json'], 'executed': False, 'benchmark_ready': False,
        'limitations': 'Package only; no independent execution adapter or model result. Curator evidence is not model input. Human/model prior exposure is unverified. Historical multi-commit range, five curated cases, not full upstream suite or authentication security evaluation. No independent benchmark claim.'}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return {'status': 'packaged_only', 'directory': str(output), 'manifest_sha256': file_hash(output/'manifest.json'),
        'executed': False, 'benchmark_ready': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reproduction', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.reproduction, args.output), indent=2))


if __name__ == '__main__':
    main()
