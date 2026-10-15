"""Review the fixed shortlist without replacing candidates or executing code."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.preparation import prepare_snapshot
from keel.candidate_review import review_sources
from keel.candidate_selection import shortlist
from keel.evaluation_protocol import registry, file_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='Fetch pinned source snapshots and compare ASTs; no model or Docker')
    parser.add_argument('--offline', action='store_true', help='Require existing snapshots with --execute')
    args = parser.parse_args()
    if args.offline and not args.execute:
        parser.error('--offline requires --execute')
    root = Path(__file__).resolve().parents[1]
    plan = json.loads((args.collection/'plan.json').read_text(encoding='utf-8'))
    selected = json.loads((args.collection/'shortlist.json').read_text(encoding='utf-8'))
    collections = json.loads((args.collection/'collections.json').read_text(encoding='utf-8'))
    if plan['development_registry_sha256'] != file_hash(root/'examples/evaluation_development_registry.json'):
        raise ValueError('Development registry changed; collection must be reviewed explicitly')
    if plan['selector_sha256'] != file_hash(root/'keel/candidate_selection.py'):
        raise ValueError('Selector changed since collection')
    if selected != shortlist(plan['policy'], registry(root), collections) or selected['status'] != 'shortlisted':
        raise ValueError('A complete reproducible shortlist is required')
    output = root/'.keel/candidate-review'/uuid.uuid4().hex
    output.mkdir(parents=True)
    print(f'Artifacts: {output}', flush=True)
    rows = [{**row, 'review': {'status': 'prepared', 'benchmark_ready': False}} for row in selected['selected']]
    report = {'prepared_only': not args.execute, 'collection': str(args.collection.resolve()),
        'collection_plan_sha256': file_hash(args.collection/'plan.json'),
        'shortlist_sha256': file_hash(args.collection/'shortlist.json'),
        'reviewer_sha256': file_hash(root/'keel/candidate_review.py'),
        'runner_sha256': file_hash(Path(__file__).resolve()), 'screening_rule': 'python-ast-change-required-v1',
        'records': rows, 'independent_tasks_ready': 0, 'benchmark_ready': False,
        'limitations': 'Curator-only source review; fixed selected IDs retained, no reserve promotion, no model calls or executable task claims.'}
    def save():
        (output/'review.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    if args.execute:
        for number, row in enumerate(rows, 1):
            print(f"[Review {number}/{len(rows)}] {row['repository']}#{row['number']}", flush=True)
            try:
                snapshots = {}
                for phase in ('base', 'gold'):
                    revision = row[phase+'_commit']
                    snapshots[phase] = prepare_snapshot(row['repository'], revision,
                        root/'.keel/independent-snapshots'/row['repository'].replace('/', '--')/revision,
                        offline=args.offline)
                row['review'] = review_sources(row, snapshots['base'], snapshots['gold'])
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                row['review'] = {'status': 'review_error', 'error': f'{type(error).__name__}: {error}', 'benchmark_ready': False}
            save()
    print(json.dumps(report, indent=2))
    return 1 if any(row['review']['status'] == 'review_error' for row in rows) else 0


if __name__ == '__main__':
    raise SystemExit(main())
