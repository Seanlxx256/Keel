"""Diagnose frozen retrieval candidates; oracle calculations are evaluation-only."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import load_swe_instance, pack_regions, region_metrics
from examples.compare_retrieval_alternatives import score


def diagnose(rows, instance, line_budget=100, cap=32):
    # Reuse the untrusted candidate validation, then evaluate without changing
    # candidate order. Relevance labels are not supplied to any retriever.
    rows = score(rows, instance)['candidates']
    core, optional, files = instance['core_regions'], instance['optional_regions'], instance['core_files']
    def metrics(regions):
        return region_metrics(regions, core, optional, files)
    def hits(regions):
        measured = metrics(regions)
        return round(measured['line_precision']*measured['predicted_unique_lines'])
    regions = [{'path': r['path'], 'start': r['start_line'], 'end': r['end_line']} for r in rows]
    capacity = sum(r['end_line']-r['start_line']+1 for r in rows)
    capped = pack_regions(rows, capacity, cap)
    packed = pack_regions(rows, line_budget, cap)
    all_hits, prefix_hits, actual_hits = hits(regions), hits(capped), hits(packed)
    core_lines = metrics([])['core_lines']
    first = next((i for i, r in enumerate(regions, 1) if hits([r])), None)
    useful = [{'rank': i, **r, 'core_overlap_lines': hits([r]),
               'prefix_core_overlap_lines': hits([{'path': r['path'], 'start': r['start'],
                    'end': min(r['end'], r['start']+cap-1)}])}
              for i, r in enumerate(regions, 1) if hits([r])]
    return {'candidate_count': len(rows), 'core_lines': core_lines,
        'first_core_overlap_rank': first,
        'full_candidate_core_lines': all_hits, 'capped_candidate_core_lines': prefix_hits,
        'emitted_core_lines': actual_hits, 'emitted_metrics': metrics(packed),
        'loss_decomposition': {'absent_from_saved_candidates': core_lines-all_hits,
            'removed_by_per_chunk_prefix_cap': all_hits-prefix_hits,
            'not_emitted_under_ranked_budget': prefix_hits-actual_hits},
        'optimistic_line_oracle': {'full_candidates': min(line_budget, all_hits),
            'capped_candidates': min(line_budget, prefix_hits),
            'gap_to_capped_line_oracle': min(line_budget, prefix_hits)-actual_hits},
        'prefix_curve': [{'k': k, 'available_candidates': min(k, len(rows)),
            'full_core_lines': hits(regions[:k]),
            'emitted_core_lines': hits(pack_regions(rows[:k], line_budget, cap))}
            for k in (1, 5, 10, 20, 60, 100)], 'core_overlapping_candidates': useful}


def analyze(source_path, external_paths, output):
    inputs = {}
    def read(path):
        path = Path(path).resolve(strict=True)
        raw = path.read_bytes()
        inputs[str(path)] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    source = read(source_path)
    source_hash = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    reports = [read(p) for p in external_paths]
    if any(r['source_sha256'] != source_hash or r.get('line_budget') != 100 or
           r.get('symbol_line_cap') != 32 for r in reports):
        raise ValueError('External source identity or packing policy mismatch')
    records, excluded, seen = [], [], set()
    for item in source['instances']:
        dataset = Path(item['measurements'][0]['sweep']).parent.parent/'instance.jsonl'
        read(dataset)
        instance = load_swe_instance(dataset, item['instance_id'], Path(item['snapshot']))
        query_hash = hashlib.sha256(instance['query'].encode()).hexdigest()
        index_refs = set()
        for measurement in item['measurements']:
            path = Path(measurement['sweep']).parent/'runs.jsonl'
            raw = path.read_bytes()
            inputs[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
            runs = [json.loads(s) for s in raw.decode('utf-8').splitlines() if s.strip()]
            selected = [r for r in runs if r['mode'] == 't1' and r['status'] == 'passed' and r['line_budget'] == 100]
            if len(selected) != 1:
                raise ValueError('Expected one historical T1 record per task/ranking')
            saved = selected[0]['result']
            index_refs.add(saved['index_ref'])
            rows = [{**r, 'start_line': r['start'], 'end_line': r['end']} for r in saved['candidates']]
            records.append({'instance': instance['id'], 'engine': 'compass_cached_'+measurement['ranking'],
                'diagnosis': diagnose(rows, instance)})
        for report in reports:
            for row in report['records']:
                if row['instance'] != instance['id'] or row['engine'].startswith('compass_cached_'):
                    continue
                key = (row['instance'], row['engine'])
                if key in seen:
                    raise ValueError('Duplicate external task/engine record')
                seen.add(key)
                if row['status'] != 'ok':
                    excluded.append({'instance': row['instance'], 'engine': row['engine'], 'status': row['status']})
                    continue
                if row['query_sha256'] != query_hash or row['index_ref'] not in index_refs or \
                        row['dataset_sha256'] != inputs[str(dataset.resolve())]:
                    raise ValueError('External task query/index/dataset identity mismatch')
                records.append({'instance': instance['id'], 'engine': row['engine'],
                                'diagnosis': diagnose(row['candidates'], instance)})
    summary = []
    for engine in sorted({r['engine'] for r in records}):
        group = [r['diagnosis'] for r in records if r['engine'] == engine]
        summary.append({'engine': engine, 'tasks': len(group),
            'tasks_with_any_saved_core_overlap': sum(r['full_candidate_core_lines'] > 0 for r in group),
            **{key: statistics.mean(r[key] for r in group) for key in (
                'full_candidate_core_lines', 'capped_candidate_core_lines', 'emitted_core_lines')},
            'mean_capped_line_oracle': statistics.mean(r['optimistic_line_oracle']['capped_candidates'] for r in group)})
    for path, expected in inputs.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Input artifact changed during analysis')
    report = {'records': records, 'summary': summary, 'excluded': excluded,
        'inputs_sha256': inputs, 'new_model_calls': 0, 'benchmark_ready': False,
        'implementation_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__), Path(__file__).parents[1]/'compass/benchmarks.py',
             Path(__file__).with_name('compare_retrieval_alternatives.py'))},
        'limitations': 'Cached exposed development tasks; core labels describe trajectory reads, not minimal fix locations. '
            'Candidate pools/chunks and query policies differ. Oracle selects gold lines and is not an executable '
            'retrieval policy or promised gain. Budget loss includes unavoidable capacity limits, not just ranking errors.'}
    output.mkdir(parents=True, exist_ok=False)
    (output/'diagnosis.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--external', nargs='+', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.source, args.external, args.output)
    print(json.dumps(result['summary'], indent=2))
