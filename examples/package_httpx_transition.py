"""Export a bounded task package from a successful curator reproduction; no inference."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples import reproduce_httpx_1588 as reproduction
from keel.evaluation_protocol import file_hash


def export(source, output):
    summary = source/'summary.json'
    report = json.loads(summary.read_text(encoding='utf-8'))
    row = report['selected_metadata']
    if (report.get('candidate') != 'encode__httpx-1588' or
        report.get('probe_passed') is not True or not reproduction.assess(report.get('executions', {})) or
        report.get('probe_sha256') != hashlib.sha256(reproduction.PROBE.encode()).hexdigest() or
        report.get('runner_sha256') != file_hash(Path(reproduction.__file__)) or
        row.get('repository') != 'encode/httpx' or row.get('number') != 1588 or
        row.get('base_commit') != '2d571046e15d3f4c4cbe5a68173cdf12e99cb3ca' or
        row.get('gold_commit') != 'd98e9e7ae7963a60ce8dc6a25cbe5f04c6438f4c'):
        raise ValueError('Matching successful three-cell reproduction required')
    images = report.get('images', {})
    if set(images) != {'old', 'new'} or any(not re.fullmatch('sha256:[0-9a-f]{64}', str(v)) for v in images.values()):
        raise ValueError('Resolved dependency image IDs required')
    # Deliberate allowlist: no PR body, gold revision, diff or curator source paths.
    task = {'id': 'httpx-1588', 'repository': 'encode/httpx',
        'base_commit': row['base_commit'],
        'goal': 'Restore HTTPX synchronous and asynchronous HTTP/1 GET and POST behavior after upgrading HTTPcore from 0.12.3 to 0.13.0. Preserve response status and body behavior. Fix library source without changing tests, dependency versions or verification infrastructure.',
        'source_scope': 'httpx/**/*.py',
        'localization': 'Repository search required; no curator file localization supplied.'}
    output.mkdir(parents=True, exist_ok=False)
    (output/'task.json').write_text(json.dumps(task, indent=2)+'\n', encoding='utf-8')
    (output/'acceptance.py').write_text(reproduction.PROBE, encoding='utf-8')
    manifest = {'schema_version': 1, 'id': task['id'],
        'files': {n: file_hash(output/n) for n in ('task.json', 'acceptance.py')},
        'acceptance': {'image': images['new'], 'timeout_seconds': 90,
            'cases': reproduction.CASES, 'versions': dict(pin.split('==') for pin in reproduction.COMMON+['httpcore==0.13.0']),
            'backend': 'docker', 'command': ['python', '-c', '<verified acceptance.py contents>']},
        'curator_receipt': {'summary_sha256': file_hash(summary),
            'shortlist_sha256': report['collection_shortlist_sha256'],
            'base_inventory': report['verified_range']['base_inventory']},
        'model_input_files': ['task.json'], 'executed': False, 'benchmark_ready': False,
        'limitations': 'Package only; no independent execution adapter or model result. Curator evidence is not model input. Human/model prior exposure is unverified. Four HTTP/1 cases, not the full upstream suite.'}
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
