"""Replay saved T1/T2 selections with the online reserved-prefix policy; no model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

from .benchmarks import load_swe_instance, pack_regions, region_metrics
from .retrieval import reserve_t1_candidates


def replay(source_path, output, *, line_budget=100, symbol_line_cap=32, reserves=(1, 2, 3)):
    if any(type(v) is not int or v < 1 or v > 100000 for v in (line_budget, symbol_line_cap)):
        raise ValueError('Positive bounded line budget and symbol cap required')
    if not reserves or len(set(reserves)) != len(reserves) or any(type(v) is not int or not 1 <= v <= 100 for v in reserves):
        raise ValueError('Choose unique reserved-prefix sizes 1..100')
    inputs = {}
    def read(path):
        path = Path(path).resolve(strict=True)
        raw = path.read_bytes()
        inputs[str(path)] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    source = read(source_path)
    records, excluded = [], []
    for item in source['instances']:
        for measurement in item.get('measurements', []):
            sweep_path = Path(measurement['sweep'])
            sweep = read(sweep_path)
            dataset = sweep_path.parent.parent/'instance.jsonl'
            read(dataset)
            instance = load_swe_instance(dataset, item['instance_id'], Path(item['snapshot']))
            if sweep['base_commit'] != instance['base_commit'] or sweep['instance_id'] != instance['id']:
                raise ValueError('Saved sweep/source identity mismatch')
            runs_path = (sweep_path.parent/'runs.jsonl').resolve(strict=True)
            raw = runs_path.read_bytes()
            inputs[str(runs_path)] = hashlib.sha256(raw).hexdigest()
            runs = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
            pairs = {}
            for run in runs:
                if run['mode'] not in ('t1', 't2'):
                    continue
                key = (run['repeat'], run['line_budget'])
                arms = pairs.setdefault(key, {})
                if run['mode'] in arms:
                    raise ValueError('Duplicate task/mode/repetition/budget')
                arms[run['mode']] = run
            for (repeat, source_budget), arms in pairs.items():
                identity = {'instance': instance['id'], 'ranking': measurement['ranking'],
                            'repeat': repeat, 'source_line_budget': source_budget}
                if set(arms) != {'t1', 't2'} or any(r['status'] != 'passed' for r in arms.values()):
                    excluded.append({**identity, 'reason': 'missing_or_failed_source_arm'})
                    continue
                if arms['t1']['result']['index_ref'] != arms['t2']['result']['index_ref']:
                    raise ValueError('T1/T2 source indices differ')
                def candidates(arm):
                    rows = arms[arm]['result']['candidates']
                    if ([r['rank'] for r in rows] != list(range(1, len(rows)+1)) or
                            len({r['id'] for r in rows}) != len(rows)):
                        raise ValueError('Saved candidates must have unique IDs and consecutive ranks')
                    return [{**r, 'start_line': r['start'], 'end_line': r['end']} for r in rows]
                initial, selected = candidates('t1'), candidates('t2')
                policies = {'t1': initial, 't2': selected}
                policies.update({f't2_reserve_{n}': reserve_t1_candidates(initial, selected, n, 100) for n in reserves})
                for policy, rows in policies.items():
                    regions = pack_regions(rows[:100], line_budget, symbol_line_cap)
                    metrics = region_metrics(regions, instance['core_regions'], instance['optional_regions'], instance['core_files'])
                    ceiling = min(line_budget, metrics['core_lines'])/metrics['core_lines'] if metrics['core_lines'] else 0
                    records.append({**identity, 'policy': policy, 'line_budget': line_budget,
                        'source_usage': arms['t1' if policy == 't1' else 't2']['result']['usage'],
                        'symbol_line_cap': symbol_line_cap, 'metrics': metrics, 'predictions': regions,
                        'budget_recall_ceiling': ceiling,
                        'recall_fraction_of_ceiling': metrics['line_recall']/ceiling if ceiling else 0})
    summary = []
    for ranking, policy in sorted({(r['ranking'], r['policy']) for r in records}):
        group = [r for r in records if r['ranking'] == ranking and r['policy'] == policy]
        tasks = sorted({r['instance'] for r in group})
        summary.append({'ranking': ranking, 'policy': policy, 'instances': len(tasks),
            **{metric: statistics.mean(statistics.mean(r['metrics'][metric] for r in group if r['instance'] == task)
                                      for task in tasks)
               for metric in ('line_recall', 'line_precision', 'hit_file_rate', 'predicted_unique_lines')}})
    for name, expected in inputs.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise ValueError('Source artifacts changed during replay')
    report = {'kind': 'fixed-trajectory selection ablation', 'new_model_calls': 0,
        'line_budget': line_budget, 'symbol_line_cap': symbol_line_cap, 'reserves': list(reserves),
        'inputs_sha256': inputs, 'implementation_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(__file__), Path(__file__).with_name('retrieval.py'), Path(__file__).with_name('benchmarks.py'))},
        'records': records, 'summary': summary, 'excluded': excluded, 'benchmark_ready': False,
        'limitations': 'Previously exposed development tasks and cached trajectories. No new retrieval/model execution or online quality claim; outline navigation is not evaluated by this replay. Never tune defaults from these labels.'}
    output.mkdir(parents=True, exist_ok=False)
    (output/'selection-ablation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--line-budget', type=int, default=100)
    parser.add_argument('--symbol-line-cap', type=int, default=32)
    args = parser.parse_args()
    report = replay(args.result, args.output_dir, line_budget=args.line_budget, symbol_line_cap=args.symbol_line_cap)
    print(json.dumps({'summary': report['summary'], 'excluded': report['excluded'], 'new_model_calls': 0}, indent=2))
