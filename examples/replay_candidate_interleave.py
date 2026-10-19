"""Offline fixed two-source candidate interleave; no label-based routing or inference."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import load_swe_instance
from examples.compare_retrieval_alternatives import score

POLICY = {'name': 'alternating_candidates', 'first': 'compass', 'weights': [1, 1],
          'deduplication': 'exact path/start/end; first occurrence', 'candidate_cap': 100,
          'line_budget': 100, 'symbol_line_cap': 32}


def interleave(primary, secondary):
    """Alternate native ranks, retaining first occurrence of exact source ranges."""
    result, seen = [], set()
    for position in range(max(len(primary), len(secondary))):
        for rows in (primary, secondary):
            if position >= len(rows):
                continue
            row = rows[position]
            key = (row['path'], row['start_line'], row['end_line'])
            if key not in seen:
                result.append(dict(row))
                seen.add(key)
            if len(result) == 100:
                return result
    return result


def replay(source, external, output):
    inputs = {}
    def raw(path):
        path = Path(path).resolve(strict=True)
        data = path.read_bytes()
        inputs[str(path)] = hashlib.sha256(data).hexdigest()
        return data
    batch = json.loads(raw(source))
    measured = json.loads(raw(external))
    if measured['line_budget'] != 100 or measured['symbol_line_cap'] != 32:
        raise ValueError('Packing policy mismatch')
    if measured['source_sha256'] != inputs[str(source.resolve())]:
        raise ValueError('External source identity mismatch')
    output.mkdir(parents=True, exist_ok=False)
    # Policy is persisted before scoring, though declared after development exposure.
    (output/'policy.json').write_text(json.dumps(POLICY, indent=2), encoding='utf-8')
    records, exclusions = [], []
    for item in batch['instances']:
        matching = [r for r in measured['records'] if r['instance'] == item['instance_id']
                    and r['engine'] == 'aider_native_tags']
        if len(matching) != 1:
            raise ValueError('Expected exactly one native Aider row')
        row = matching[0]
        if row['status'] != 'ok':
            exclusions.append({'instance': item['instance_id'], 'status': row['status']})
            continue
        paths = [Path(m['sweep']) for m in item['measurements'] if m['ranking'] == 'code-aware']
        if len(paths) != 1:
            raise ValueError('Expected one Compass ranking')
        dataset = paths[0].parent.parent/'instance.jsonl'
        raw(dataset)
        runs = [json.loads(s) for s in raw(paths[0].parent/'runs.jsonl').decode().splitlines() if s.strip()]
        selected = [r for r in runs if r['mode'] == 't1' and r['status'] == 'passed' and r['line_budget'] == 100]
        if len(selected) != 1:
            raise ValueError('Ambiguous historical Compass result')
        saved = selected[0]['result']
        instance = load_swe_instance(dataset, item['instance_id'], Path(item['snapshot']))
        if row['index_ref'] != saved['index_ref'] or row['dataset_sha256'] != inputs[str(dataset.resolve())] or \
                row['query_sha256'] != hashlib.sha256(instance['query'].encode()).hexdigest():
            raise ValueError('Native query/index/dataset identity mismatch')
        primary = [{**r, 'start_line': r['start'], 'end_line': r['end']} for r in saved['candidates']]
        baseline, aider = score(primary, instance), score(row['candidates'], instance)
        for actual, historical in [(baseline['metrics'], saved['metrics']), (aider['metrics'], row['metrics'])]:
            if any(abs(value-historical[k]) > 1e-12 for k, value in actual.items()):
                raise ValueError('Historical score does not reproduce')
        mixed = score(interleave(baseline['candidates'], aider['candidates']), instance)
        primary_keys = {(r['path'], r['start_line'], r['end_line']) for r in baseline['candidates']}
        secondary_keys = {(r['path'], r['start_line'], r['end_line']) for r in aider['candidates']}
        delta = mixed['metrics']['line_recall']-baseline['metrics']['line_recall']
        records.append({'instance': instance['id'], 'baseline': baseline['metrics'], 'aider': aider['metrics'],
            'interleaved': mixed['metrics'], 'recall_delta': delta,
            'outcome': 'improved' if delta > 1e-12 else 'regressed' if delta < -1e-12 else 'tied',
            'exact_candidate_overlap': len(primary_keys & secondary_keys),
            'primary_candidates': len(primary_keys), 'secondary_candidates': len(secondary_keys),
            'predictions': mixed['predictions'], 'candidates': mixed['candidates']})
    summary = {arm: {k: statistics.mean(r[arm][k] for r in records) if records else None
        for k in ('line_recall', 'line_precision', 'hit_file_rate')} for arm in ('baseline','aider','interleaved')}
    summary['outcomes'] = {label: sum(r['outcome']==label for r in records)
                           for label in ('improved','tied','regressed')}
    for path, expected in inputs.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Historical input changed during replay')
    report = dict(status='completed', policy=POLICY, records=records, summary=summary,
        paired_tasks=len(records), exclusions=exclusions, inputs_sha256=inputs,
        new_model_calls=0, benchmark_ready=False, default_promoted=False,
        implementation_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__), Path(__file__).with_name('compare_retrieval_alternatives.py'),
             Path(__file__).parents[1]/'compass/benchmarks.py')},
        limitations='Post-hoc exposed development sample. Fixed one-policy replay, not held-out. '
        'No parameter search or per-task policy selection. Exact-span deduplication does not merge '
        'overlapping unequal chunks. Aider rank component differs from its rendered map/full Agent.')
    (output/'comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--external', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = replay(args.source, args.external, args.output)
    print(json.dumps(result['summary'], indent=2))
