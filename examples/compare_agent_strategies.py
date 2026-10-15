"""Compare saved proposal/tool-loop runs without model or Docker requests."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def compare(left, right):
    loaded = []
    for directory in (left, right):
        manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        result = json.loads((directory/'results.json').read_text(encoding='utf-8'))
        if result['prepared_only'] or manifest['strategy'] != result['strategy']:
            raise ValueError('Completed execution reports with matching strategy required')
        loaded.append((manifest, result))
    if {m['strategy'] for m, _ in loaded} != {'proposal', 'tool-loop'}:
        raise ValueError('One proposal and one tool-loop run required')
    if loaded[0][1]['reproduction_sha256'] != loaded[1][1]['reproduction_sha256']:
        raise ValueError('Reproduction differs')
    if loaded[0][0]['implementation_sha256'] != loaded[1][0]['implementation_sha256']:
        raise ValueError('Implementation differs; rerun both strategies on the same revision')
    indexed = []
    for manifest, result in loaded:
        tasks = {t['id']: t for t in manifest['tasks']}
        records = {r['id']: r for r in result['records']}
        if len(tasks) != len(manifest['tasks']) or len(records) != len(result['records']) or tasks.keys() != records.keys():
            raise ValueError('Duplicate or missing task records')
        indexed.append((tasks, records))
    if indexed[0][0].keys() != indexed[1][0].keys():
        raise ValueError('Planned task sets differ; failed tasks must not be dropped')
    pairs = []
    for identity in sorted(indexed[0][0]):
        tasks = [index[0][identity] for index in indexed]
        for field in ('source_sha256', 'target', 'group'):
            if tasks[0][field] != tasks[1][field]:
                raise ValueError(f'{identity}: {field} differs')
        configs = []
        for task in tasks:
            config = dict(task['config'])
            config.pop('mode')
            scope = config.pop('proposal', {})
            if scope.get('dependencies'):
                raise ValueError('Dependency evidence is asymmetric; disable it for both strategies')
            configs.append(config)
        if configs[0] != configs[1]:
            raise ValueError(f'{identity}: shared goal/model/budget/acceptance/settings differ')
        identities = [result.get('model_identity') for _, result in loaded]
        if not identities[0] or identities[0] != identities[1]:
            raise ValueError('Configured model identity differs or is missing')
        pair = {'id': identity, 'group': tasks[0]['group'], 'strategies': {}}
        for (manifest, _), (_, records) in zip(loaded, indexed):
            record = records[identity]
            if record['status'] in ('prepared', 'running'):
                raise ValueError('Run is not terminal')
            pair['strategies'][manifest['strategy']] = {
                key: record.get(key) for key in ('status', 'executed', 'passed', 'failure', 'error',
                                                'budget', 'seconds_including_baseline', 'trace_metrics')}
        pairs.append(pair)
    return {'pairs': pairs, 'planned_pairs': len(pairs), 'benchmark_ready': False,
        'limitations': 'Saved harness outcomes, not independently reverified artifacts. Same inputs and limits; '
        'proposal uses localized one-call evidence, tool-loop uses role sessions and tools. Both retain safety '
        'checks and Docker acceptance. Not a runtime-versus-no-runtime or isolated component ablation. '
        'Remote weight identity is unverified; repeated tasks do not add independent coverage.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proposal', type=Path)
    parser.add_argument('tool_loop', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = compare(args.proposal, args.tool_loop)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
