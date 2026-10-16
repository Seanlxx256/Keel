"""Read static dependency contracts from a trial's fixed image; never invokes a model."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.core import Budget, Ledger, Limits, Trace
from keel.dependency_evidence import collect, referenced_calls, validate_requests
from keel.evaluation_protocol import file_hash
from keel.execution import CommandRunner
from keel.workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', required=True, type=Path)
    parser.add_argument('--distribution', required=True)
    parser.add_argument('--module', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    trial = args.trial.resolve()
    prepared = json.loads((trial/'prepared.json').read_text(encoding='utf-8'))
    result = json.loads((trial/'results.json').read_text(encoding='utf-8'))
    changed = result.get('changed_files', [])
    if not changed:
        parser.error('A saved candidate with changed files is required')
    repo = trial/'repo'
    symbols = set()
    source_hashes = {}
    for name in changed:
        path = (repo/name).resolve()
        if name not in prepared['source'] or not path.is_relative_to(repo):
            raise ValueError('Changed source must be a declared existing workspace file')
        source_hashes[name] = file_hash(path)
        symbols.update(referenced_calls(path.read_bytes().decode('utf-8'), args.module))
    version = prepared['acceptance']['versions'][args.distribution]
    requests = [{'distribution': args.distribution, 'version': version,
        'symbols': sorted(symbols), 'include_methods': True}]
    validate_requests(requests)
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker)+os.pathsep+os.environ.get('PATH', '')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'new_model_calls': 0, 'requests': requests, 'source_sha256': source_hashes,
        'image': prepared['config']['execution']['image'], 'status': 'running'}
    with closing(Ledger(args.output/'ledger.sqlite')) as ledger:
        workspace = Workspace(repo, Budget(Limits()), ledger, Trace(args.output/'trace.jsonl'),
            runner=CommandRunner(prepared['config']['execution']))
        before = workspace.snapshot()
        try:
            report['evidence'] = collect(workspace, requests)
            report['status'] = 'collected'
        except Exception as error:
            report.update(status='failed', error=f'{type(error).__name__}: {error}')
        report['source_unchanged'] = before == workspace.snapshot()
    (args.output/'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'collected' and report['source_unchanged'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
