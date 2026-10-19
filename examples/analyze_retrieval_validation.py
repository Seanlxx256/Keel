"""Audit completed retrieval artifacts without inference or parameter selection."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def analyze(run, output):
    identities = {}
    def read(path):
        raw = path.read_bytes()
        identities[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    validation = read(run/'validation.json')
    fusion = read(run/'fusion/fusion.json')
    if fusion['status'] != 'completed':
        raise ValueError('Completed fusion replay required')
    for path, expected in fusion['inputs_sha256'].items():
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('Historical input changed: '+path)
        identities[path] = actual
    records = fusion['records']
    keys = [(r['engine'], r['instance']) for r in records]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate engine/task')
    engines = sorted({r['engine'] for r in records})
    sets = [{r['instance'] for r in records if r['engine'] == e} for e in engines]
    common = set.intersection(*sets) if sets else set()
    details, summaries = [], []
    for engine in engines:
        group = [r for r in records if r['engine'] == engine and r['instance'] in common]
        deltas = [r['fused']['line_recall']-r['baseline']['line_recall'] for r in group]
        for row, delta in zip(group, deltas):
            details.append({'engine': engine, 'instance': row['instance'],
                **{arm: row[arm] for arm in ('baseline', 'reranked', 'fused')},
                'fusion_recall_delta': delta,
                'outcome': 'improved' if delta > 1e-12 else 'regressed' if delta < -1e-12 else 'tied'})
        summaries.append({'engine': engine, 'paired_tasks': len(group),
            'mean_fusion_recall_delta': statistics.mean(deltas) if deltas else None,
            'outcomes': {label: sum(r['outcome'] == label for r in details if r['engine'] == engine)
                         for label in ('improved', 'tied', 'regressed')},
            'leave_one_out_delta': {r['instance']: statistics.mean(deltas[:i]+deltas[i+1:])
                for i, r in enumerate(group) if len(group) > 1}})
    report = {'status': 'analyzed', 'common_tasks': sorted(common), 'records': details,
        'summary': summaries, 'original_status': validation['status'],
        'retained_failures': [r for r in validation['records'] if r['status'] != 'baseline_ready'],
        'excluded_engines': validation.get('excluded_engines', []), 'inputs_sha256': identities,
        'new_model_calls': 0, 'default_promoted': False, 'benchmark_ready': False,
        'limitations': 'Post-hoc development analysis, not a significance test or held-out result. '
            'Leave-one-out sensitivity is descriptive and cannot select a runtime policy. '
            'No new retrieval, model inference, label edits or ranking changes.'}
    lines = ['# Frozen retrieval validation analysis', '',
        'Post-hoc analysis; no policy promoted. Values below are recall percentages.', '',
        '| Engine | Task | Original | Reranked | Fused | Fusion delta (pp) |',
        '|---|---|---:|---:|---:|---:|']
    for r in details:
        lines.append('| '+r['engine']+' | '+r['instance']+' | '+
            ' | '.join(f"{100*r[a]['line_recall']:.3f}" for a in ('baseline','reranked','fused'))+
            f" | {100*r['fusion_recall_delta']:+.3f} |")
    lines += ['', '## Sensitivity', '']
    for s in summaries:
        lines.append(f"- {s['engine']}: {s['outcomes']}; leave-one-task-out mean deltas (percentage points): "+
            ', '.join(f'{k}: {v*100:+.3f}' for k,v in s['leave_one_out_delta'].items()))
    lines += ['', '## Retained limitations', '', report['limitations'], '',
        f"Original run status: {validation['status']}. Input failures: {len(report['retained_failures'])}.",
        '', '## Next validation', '',
        'Keep original Compass as the default. Freeze disjoint task IDs and the existing ranking, '
        'model, line budget and fusion policy before execution. Compare all three arms on the same '
        'tasks; report per-task wins/losses, means, precision and file hits. Do not tune on this report. '
        'A retrieval gain still requires separate end-to-end repair evaluation.']
    for path, expected in identities.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Input changed during analysis: '+path)
    output.mkdir(parents=True, exist_ok=False)
    (output/'analysis.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (output/'analysis.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.run.resolve(), args.output.resolve())
    print(json.dumps({'status': result['status'], 'summary': result['summary'], 'new_model_calls': 0}, indent=2))
