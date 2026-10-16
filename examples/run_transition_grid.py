"""Prepare or execute a fixed context-cap grid. Preparation never invokes providers."""
import argparse
import copy
import json
from pathlib import Path
import random
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.run_transition_task import prepare, execute, inventory
from keel.core import digest
from keel.evaluation_protocol import file_hash, implementation_hashes


def comparable(frozen):
    value = copy.deepcopy(frozen)
    value['config']['agent'].pop('max_context_bytes', None)
    return value


def prepare_grid(root, package, model, output, caps, repeats=1, seed=42):
    if (not isinstance(caps, list) or not 2 <= len(caps) <= 6 or len(set(caps)) != len(caps) or
        any(type(c) is not int or not 1024 <= c <= 128000 for c in caps) or
        type(repeats) is not int or not 1 <= repeats <= 3 or type(seed) is not int):
        raise ValueError('Require 2..6 unique caps (1024..128000), 1..3 repetitions and integer seed')
    output.mkdir(parents=True, exist_ok=False)
    rows, common = [], None
    for repeat in range(1, repeats+1):
        for cap in sorted(caps):
            name = f'runs/cap-{cap}-repeat-{repeat}'
            frozen = prepare(root, package, model, output/name, strategy='localized-proposal',
                baseline_feedback=True, require_change=True, dependency_modules=['httpcore'],
                select_contracts=True, max_context_bytes=cap)
            key = digest(comparable(frozen))
            if common is not None and key != common:
                raise ValueError('Grid inputs differ beyond context cap')
            common = key
            rows.append({'directory': name, 'cap_bytes': cap, 'repeat': repeat,
                'prepared_sha256': file_hash(output/name/'prepared.json')})
    random.Random(seed).shuffle(rows)
    plan = {'runs': rows, 'seed': seed, 'common_sha256': common,
        'implementation': implementation_hashes(root), 'unique_tasks': 1, 'heldout_tasks': 0,
        'benchmark_ready': False, 'scope': 'One observed development task, context-cap sweep; repetitions are not new tasks'}
    (output/'grid.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    (output/'grid.sha256').write_text(file_hash(output/'grid.json'), encoding='ascii')
    return plan


def execute_grid(root, output):
    if file_hash(output/'grid.json') != (output/'grid.sha256').read_text():
        raise ValueError('Grid manifest changed')
    plan = json.loads((output/'grid.json').read_text(encoding='utf-8'))
    if implementation_hashes(root) != plan['implementation']:
        raise ValueError('Implementation changed after grid preparation')
    # Check every arm before spending the first provider call.
    for row in plan['runs']:
        directory = (output/row['directory']).resolve()
        if not directory.is_relative_to(output.resolve()):
            raise ValueError('Grid directory escapes output')
        frozen = json.loads((directory/'prepared.json').read_text(encoding='utf-8'))
        if (file_hash(directory/'prepared.json') != row['prepared_sha256'] or
            digest(comparable(frozen)) != plan['common_sha256'] or
            frozen['config']['agent']['max_context_bytes'] != row['cap_bytes'] or
            inventory(directory/'repo') != frozen['source'] or (directory/'execution-started.json').exists()):
            raise ValueError('Prepared grid arm differs or was already executed')
    with (output/'grid-started.json').open('x', encoding='utf-8') as stream:
        json.dump({'started_unix': time.time()}, stream)
    report = {'records': [{**row, 'status': 'pending', 'passed': False} for row in plan['runs']],
        'planned_runs': len(plan['runs']), 'unique_tasks': 1, 'heldout_tasks': 0, 'benchmark_ready': False}
    def save():
        (output/'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        lines = ['# Context-cap development sweep', '',
            'One observed task; failures retained. Repetitions are not independent tasks.', '',
            '| Cap bytes | Repeat | Status | Pass | Calls | Tokens | Seconds incl. baseline | Max input bytes | Failure |',
            '| ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |']
        for row in report['records']:
            budget = row.get('budget', {})
            failure = row.get('failure') or {}
            lines.append(f"| {row['cap_bytes']} | {row['repeat']} | {row['status']} | {row['passed']} | "
                f"{budget.get('model_calls', '-')} | {budget.get('tokens', '-')} | "
                f"{row.get('seconds_including_baseline', '-')} | {row.get('max_input_bytes', '-')} | "
                f"{failure.get('stage', '')}/{failure.get('category', '')} |")
        (output/'results.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    save()
    for i, row in enumerate(report['records'], 1):
        print(f'[Grid {i}/{len(report["records"])}] cap={row["cap_bytes"]} repeat={row["repeat"]}', flush=True)
        directory = output/row['directory']
        started = time.monotonic()
        try:
            outcome = execute(root, directory)
            row.update(outcome)
            trace = directory/'run/trace.jsonl'
            events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
            row['max_input_bytes'] = max((e['input_bytes'] for e in events if e['event'] == 'llm_call_started'), default=0)
        except Exception as error:
            row.update(status='runner_error', passed=False, error=f'{type(error).__name__}: {error}')
        row['seconds_including_baseline'] = round(time.monotonic()-started, 3)
        save()
    report['all_passed'] = all(row['passed'] for row in report['records'])
    save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--model-config', type=Path)
    parser.add_argument('--caps', type=int, nargs='+')
    parser.add_argument('--repeats', type=int)
    parser.add_argument('--seed', type=int)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.execute:
        if args.package or args.model_config or args.caps or args.repeats is not None or args.seed is not None:
            parser.error('Execution uses frozen grid only')
        report = execute_grid(root, args.output)
    else:
        if not args.package or not args.model_config:
            parser.error('Preparation requires --package and --model-config')
        plan = prepare_grid(root, args.package, args.model_config, args.output,
            args.caps if args.caps is not None else [12000, 24000, 48000],
            args.repeats if args.repeats is not None else 1, args.seed if args.seed is not None else 42)
        report = {'status': 'prepared_only', 'planned_runs': len(plan['runs']),
            'caps': sorted({r['cap_bytes'] for r in plan['runs']}), 'new_model_calls': 0,
            'normal_model_calls_if_all_stages_reached': 4*len(plan['runs'])}
    print(json.dumps(report, indent=2))
    return 1 if args.execute and not report['all_passed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
