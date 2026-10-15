"""Paired, model-free measurement of local observation memoization."""
import argparse
import hashlib
import platform
import sys
import json
from pathlib import Path
import random
import statistics
import time
import uuid

from .core import Budget, Ledger, Limits, Trace, digest
from .workspace import Workspace


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in {'cache_hit', 'repeat_count'}}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def run_benchmark(output, *, files=64, lines=128, repeats=5, trials=3, seed=42, progress=None):
    if any(type(v) is not int or v <= 0 for v in [files, lines, repeats, trials]):
        raise ValueError('Fixture sizes, repetitions and trials must be positive integers')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    repo = output / 'repo'
    repo.mkdir()
    meta = repo / '.keel'
    meta.mkdir()
    for i in range(files):
        source = 'VERSION = 1\n' + ''.join(f'value_{j} = {i + j}\n' for j in range(lines))
        (repo / f'module{i:04d}.py').write_text(source, encoding='utf-8')
    target = repo / 'module0000.py'
    initial = target.read_bytes()
    initial_ref = digest({p.name: digest(p.read_text(encoding='utf-8')) for p in sorted(repo.glob('*.py'))})
    first = random.Random(seed).choice([True, False])
    records = []
    for trial in range(trials):
        order = [first, not first] if trial % 2 == 0 else [not first, first]
        for enabled in order:
            if progress:
                progress({"trial": trial + 1, "trials": trials, "memoization": enabled})
            target.write_bytes(initial)
            run_dir = meta / f'{trial}-{enabled}'
            run_dir.mkdir()
            ledger = Ledger(run_dir / 'ledger.sqlite')
            try:
                ws = Workspace(repo, Budget(Limits(max_wallclock=600, max_tool_calls=100000)),
                               ledger, Trace(run_dir / 'trace.jsonl'), memoization=enabled)
                observed = []
                started = time.perf_counter()
                for phase in range(2):
                    for _ in range(repeats):
                        observed.extend([semantic(ws.read(target.name)), semantic(ws.list_files()),
                                         semantic(ws.search('ABSENT_NEEDLE_789'))])
                    if phase == 0:
                        ws.replace(target.name, 'VERSION = 1', 'VERSION = 2')
                seconds = time.perf_counter() - started
                records.append({'trial': trial, 'memoization': enabled, 'seconds': seconds,
                                'semantic_output_sha256': digest(observed),
                                'correct_final_source': target.read_bytes() == initial.replace(b'VERSION = 1', b'VERSION = 2', 1),
                                'tools': ws.tool_metrics, 'budget': ws.budget.report(),
                                'snapshot_calls': ws.snapshot_calls, 'snapshot_bytes': ws.snapshot_bytes,
                                'ledger': ledger.statistics()})
            finally:
                ledger.close()
    paired = all(len({r['semantic_output_sha256'] for r in records if r['trial'] == t}) == 1
                 for t in range(trials))
    summary = {}
    for enabled in [False, True]:
        rows = [r for r in records if r['memoization'] == enabled]
        summary['on' if enabled else 'off'] = {
            'median_seconds': statistics.median(r['seconds'] for r in rows),
            'requests_per_trial': sum(v['requests'] for v in rows[0]['tools'].values()),
            'computations_per_trial': sum(v['computations'] for v in rows[0]['tools'].values()),
            'cache_hits_per_trial': sum(v['cache_hits'] for v in rows[0]['tools'].values()),
            'snapshot_bytes_per_trial': rows[0]['snapshot_bytes']}
    ratio = summary['on']['median_seconds'] / summary['off']['median_seconds']
    result = {'environment': {'python': platform.python_version(), 'platform': platform.platform()},
              'implementation_sha256': {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                                        for name in ['memory_benchmark.py', 'workspace.py', 'core.py']},
              'all_passed': paired and all(r['correct_final_source'] for r in records),
              'semantic_outputs_equal': paired, 'fixture': {'files': files, 'lines_per_file': lines,
              'repeats_per_phase': repeats, 'phases': 2, 'trials': trials, 'seed': seed,
              'initial_content_sha256': initial_ref}, 'summary': summary, 'on_over_off_time_ratio': ratio,
              'records': records,
              'limitations': 'Synthetic direct Workspace calls, not agent trajectories. Both modes retain fingerprint guards and budget/trace costs. Computations mean decode/list/scan invocations, not physical disk reads. File reads and fingerprints still read bytes on cache hits. OS caches uncontrolled; no model-token, duplicate-request-rate or task-success improvement claim.'}
    (output / 'benchmark.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    report = '# Local memoization paired measurement\n\n'
    report += '| Mode | Median seconds | Requests | Computations | Hits |\n| --- | ---: | ---: | ---: | ---: |\n'
    for mode, row in summary.items():
        report += f"| {mode} | {row['median_seconds']:.6f} | {row['requests_per_trial']} | {row['computations_per_trial']} | {row['cache_hits_per_trial']} |\n"
    report += f'\nSemantic outputs equal: {paired}. On/off median time ratio: {ratio:.4f}.\n\n' + result['limitations'] + '\n'
    (output / 'benchmark.md').write_text(report, encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('.keel/memory-bench') / uuid.uuid4().hex)
    parser.add_argument('--files', type=int, default=64)
    parser.add_argument('--lines', type=int, default=128)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--trials', type=int, default=3)
    args = parser.parse_args()
    result = run_benchmark(args.output_dir, files=args.files, lines=args.lines,
                           repeats=args.repeats, trials=args.trials, progress=lambda state: print(f"[Memory] {state}", file=sys.stderr, flush=True))
    print(f'Artifacts: {args.output_dir.resolve()}')
    print(json.dumps({k: v for k, v in result.items() if k != 'records'}, indent=2))
    return 0 if result['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
