"""Offline fixed equal-weight rank fusion; no retrieval, inference or gold-based selection."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import load_swe_instance
from examples.compare_retrieval_alternatives import score
from examples.reranker_worker import stable_order


def fuse_order(reranked_order):
    count = len(reranked_order)
    if any(type(i) is not int for i in reranked_order) or sorted(reranked_order) != list(range(count)):
        raise ValueError('Expected a complete candidate permutation')
    rank = {candidate: position for position, candidate in enumerate(reranked_order, 1)}
    values = [1/(60+i+1)+1/(60+rank[i]) for i in range(count)]
    return sorted(range(count), key=lambda i: (-values[i], i))


def replay(source, external, evaluation, output):
    inputs = {}
    def raw(path):
        path = Path(path).resolve(strict=True)
        value = path.read_bytes()
        inputs[str(path)] = hashlib.sha256(value).hexdigest()
        return value
    def read(path):
        return json.loads(raw(path))
    saved = read(evaluation)
    if saved['status'] != 'completed' or saved['line_budget'] != 100 or saved['symbol_line_cap'] != 32:
        raise ValueError('Completed reranking evaluation with matching packing policy required')
    for path, digest in saved['inputs_sha256'].items():
        if hashlib.sha256(raw(path)).hexdigest() != digest:
            raise ValueError('Historical reranking input changed: '+path)
    batch = read(source)
    measured = [read(p) for p in external]
    for path in [source, *external]:
        if saved['inputs_sha256'].get(str(path.resolve())) != inputs[str(path.resolve())]:
            raise ValueError('Selected source/external report was not used in reranking')
    worker = read(evaluation.parent/'worker-result.json')
    request_path = evaluation.parent/'query-code-only.json'
    request = read(request_path)
    if worker['status'] != 'completed' or worker['input_sha256'] != inputs[str(request_path.resolve())]:
        raise ValueError('Worker request identity mismatch')
    def unique(rows, label):
        keyed = {r['id']: r for r in rows}
        if len(keyed) != len(rows):
            raise ValueError('Duplicate '+label)
        return keyed
    requests = unique(request['jobs'], 'request job')
    responses = unique(worker['jobs'], 'response job')
    if requests.keys() != responses.keys():
        raise ValueError('Worker job coverage mismatch')
    tasks = {r['instance_id']: r for r in batch['instances']}
    records, seen = [], set()
    for row in saved['records']:
        job_id = row['instance']+':'+row['engine']
        if job_id in seen:
            raise ValueError('Duplicate evaluation job')
        seen.add(job_id)
        item = tasks[row['instance']]
        dataset = Path(item['measurements'][0]['sweep']).parent.parent/'instance.jsonl'
        raw(dataset)
        instance = load_swe_instance(dataset, row['instance'], Path(item['snapshot']))
        if row['engine'] == 'compass_cached_code-aware':
            paths = [Path(m['sweep']).parent/'runs.jsonl' for m in item['measurements'] if m['ranking'] == 'code-aware']
            if len(paths) != 1:
                raise ValueError('Expected one Compass source ranking')
            runs = [json.loads(s) for s in raw(paths[0]).decode().splitlines() if s.strip()]
            selected = [r for r in runs if r['mode'] == 't1' and r['status'] == 'passed' and r['line_budget'] == 100]
            if len(selected) != 1 or selected[0]['result']['index_ref'] != row['index_ref']:
                raise ValueError('Historical Compass identity mismatch')
            candidates = [{**r, 'start_line': r['start'], 'end_line': r['end']}
                          for r in selected[0]['result']['candidates']]
        else:
            selected = [r for report in measured for r in report['records']
                        if r['instance'] == row['instance'] and r['engine'] == row['engine'] and r['status'] == 'ok']
            if len(selected) != 1 or selected[0]['index_ref'] != row['index_ref']:
                raise ValueError('External candidate identity mismatch')
            candidates = selected[0]['candidates']
        baseline = score(candidates, instance)
        candidates = baseline['candidates']
        req, resp = requests[job_id], responses[job_id]
        if req['query'] != instance['query'] or len(req['documents']) != len(candidates):
            raise ValueError('Scored query/candidate count mismatch')
        # Regenerate model inputs from unchanged source to establish candidate
        # identity. No model sees the relevance labels read by this scorer.
        for candidate, document in zip(candidates, req['documents']):
            lines = (Path(instance['repo'])/candidate['path']).read_bytes().decode('utf-8').splitlines(keepends=True)
            text = candidate['path']+'\n'+''.join(lines[candidate['start_line']-1:candidate['end_line']])
            if text != document['text'] or hashlib.sha256(text.encode()).hexdigest() != document['text_sha256']:
                raise ValueError('Scored source text changed')
        order = stable_order(row['scores'], len(candidates))
        if order != row['order'] or order != resp['order'] or row['scores'] != resp['scores']:
            raise ValueError('Saved scoring/order mismatch')
        reranked = score([candidates[i] for i in order], instance)
        for arm, result in [('baseline', baseline), ('reranked', reranked)]:
            if any(abs(value-row[arm][key]) > 1e-12 for key, value in result['metrics'].items()):
                raise ValueError('Saved metrics do not reproduce')
        fusion_order = fuse_order(order)
        fused = score([candidates[i] for i in fusion_order], instance)
        records.append({'instance': row['instance'], 'engine': row['engine'],
            'candidate_count': len(candidates), 'baseline': baseline['metrics'],
            'reranked': reranked['metrics'], 'fused': fused['metrics'],
            'fusion_order': fusion_order, 'predictions': fused['predictions']})
    if seen != requests.keys():
        raise ValueError('Evaluation job coverage mismatch')
    summary = []
    for engine in sorted({r['engine'] for r in records}):
        group = [r for r in records if r['engine'] == engine]
        differences = [r['fused']['line_recall']-r['baseline']['line_recall'] for r in group]
        summary.append({'engine': engine, 'paired_tasks': len(group),
            'recall_outcomes_vs_baseline': {'improved': sum(d > 1e-12 for d in differences),
                'tied': sum(abs(d) <= 1e-12 for d in differences), 'regressed': sum(d < -1e-12 for d in differences)},
            **{arm: {key: statistics.mean(r[arm][key] for r in group) for key in
                ('line_recall', 'line_precision', 'hit_file_rate')} for arm in ('baseline', 'reranked', 'fused')}})
    for path, expected in inputs.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Input changed during replay')
    report = {'status': 'completed', 'policy': {'name': 'equal_weight_rrf', 'constant': 60,
        'weights': [1, 1], 'tie_break': 'baseline rank'}, 'records': records, 'summary': summary,
        'inputs_sha256': inputs, 'new_model_calls': 0, 'source_inference_pairs': worker['pair_count'],
        'benchmark_ready': False, 'source_exclusions': saved.get('excluded', []),
        'implementation_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__), Path(__file__).with_name('reranker_worker.py'),
             Path(__file__).with_name('compare_retrieval_alternatives.py'),
             Path(__file__).parents[1]/'compass/benchmarks.py')},
        'limitations': 'Fixed policy declared after inspecting development reranker results; not held-out. '
            'No parameter search, candidate fusion, new inference, changed snippets or runtime promotion. '
            'RRF does not guarantee preserving baseline quality or top-ranked candidates.'}
    output.mkdir(parents=True, exist_ok=False)
    (output/'fusion.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--external', required=True, nargs='+', type=Path)
    parser.add_argument('--evaluation', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = replay(args.source, args.external, args.evaluation, args.output)
    print(json.dumps(result['summary'], indent=2))
