"""Export a bounded task package from a successful curator reproduction; no inference."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples import reproduce_django_13586 as reproduction
from keel.evaluation_protocol import file_hash


def export(source, output):
    summary = source/'summary.json'
    report = json.loads(summary.read_text(encoding='utf-8'))
    row = report['selected_metadata']
    if (report.get('candidate') != 'django__django-13586' or
        report.get('probe_passed') is not True or not reproduction.assess(report.get('executions', {})) or
        report.get('probe_sha256') != hashlib.sha256(reproduction.PROBE.encode()).hexdigest() or
        report.get('runner_sha256') != file_hash(Path(reproduction.__file__)) or
        row.get('repository') != 'django/django' or row.get('number') != 13586 or
        row.get('base_commit') != '0b4fe82c7405ba96f2eb25b954a8f498cc8364b3' or
        row.get('gold_commit') != 'e17ee4468875077b90b70bb6a589ebad7493f757'):
        raise ValueError('Matching successful three-cell reproduction required')
    images = report.get('images', {})
    if set(images) != {'old', 'new'} or any(not re.fullmatch('sha256:[0-9a-f]{64}', str(v)) for v in images.values()):
        raise ValueError('Resolved dependency image IDs required')
    # Deliberate allowlist: no PR body, gold revision, diff or curator source paths.
    task = {'id': 'django-13586', 'repository': 'django/django',
        'base_commit': row['base_commit'],
        'goal': 'Restore concurrent dispatch of independent synchronous static-response callbacks from Django async handling after upgrading asgiref from 3.2.10 to 3.3.0. Concurrent independent requests must return their distinct response bodies without rendezvous failure. Preserve response behavior. Fix library source without changing tests, dependencies or verification infrastructure.',
        'source_scope': 'django/**/*.py',
        'localization': 'Repository search required; no curator file localization supplied.'}
    output.mkdir(parents=True, exist_ok=False)
    (output/'task.json').write_text(json.dumps(task, indent=2)+'\n', encoding='utf-8')
    (output/'acceptance.py').write_text(reproduction.PROBE, encoding='utf-8')
    manifest = {'schema_version': 1, 'id': task['id'],
        'files': {n: file_hash(output/n) for n in ('task.json', 'acceptance.py')},
        'acceptance': {'image': images['new'], 'timeout_seconds': 90,
            'cases': reproduction.CASES, 'versions': dict(pin.split('==') for pin in reproduction.COMMON+['asgiref==3.3.0']),
            'baseline_errors': [{'case': 'parallel_static_responses', 'type': 'BrokenBarrierError'}],
            'backend': 'docker', 'command': ['python', '-c', '<verified acceptance.py contents>']},
        'curator_receipt': {'summary_sha256': file_hash(summary),
            'shortlist_sha256': report['collection_shortlist_sha256'],
            'base_inventory': report['verified_range']['base_inventory']},
        'model_input_files': ['task.json'], 'executed': False, 'benchmark_ready': False,
        'limitations': 'Package only; no independent execution adapter or model result. Curator evidence is not model input. Human/model prior exposure is unverified. One instrumented concurrent callback case, not full static serving or the upstream suite.'}
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
