"""Run Keel against a generic factory artifact, without discovery or rebuilding."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.run_autonomous_campaign import solver_config
from keel.campaign_reporting import trajectory
from keel.core import Budget, Limits
from keel.models import from_config
from keel.runtime import run
from keel.task_factory import inventory, installed_versions, probe, safe_path, transition_passed, validate_recipe


def load_factory(directory):
    factory = json.loads((directory/'factory.json').read_text(encoding='utf-8'))
    if factory.get('status') != 'transition_verified':
        raise ValueError('Factory has no verified transition')
    validate_recipe(factory['recipe'])
    for phase in ('old', 'new'):
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', factory['images'][phase]):
            raise ValueError('Immutable Docker image IDs required')
    roots = factory['test_roots']
    if not roots or any(root not in {'tests', 'test', 'testing'} for root in roots):
        raise ValueError('Invalid frozen test roots')
    frozen = factory['frozen_tests']
    if not frozen:
        raise ValueError('Frozen acceptance inventory required')
    for phase in ('base', 'gold'):
        source = directory/phase
        actual = inventory(source)
        acceptance = {name: sha for name, sha in actual.items()
                      if name.split('/')[0] in roots or name == 'conftest.py'}
        for name in frozen:
            safe_path(source, name)
        if acceptance != frozen:
            raise ValueError('Frozen acceptance changed in ' + phase)
    return factory


def execute(directory, output, model_config, cap=24000):
    if output.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Trial output must be outside the factory directory')
    factory = load_factory(directory)
    model = from_config(model_config)
    output.mkdir(parents=True, exist_ok=False)
    budget = Budget(Limits(max_wallclock=900, max_model_calls=30, max_tokens=180000, max_tool_calls=80))
    report = {'status': 'preflight', 'passed': False, 'benchmark_ready': False,
              'scope': 'Exploratory repair of a factory artifact; no held-out or production claim.'}
    try:
        # Recheck actual images and all three cells before spending model calls.
        cells = {}
        for phase in ('old', 'new'):
            budget.charge_tool()
            installed_versions(factory['images'][phase], factory['recipe'], phase,
                               directory/'base', min(30, budget.remaining), output/f'versions-{phase}.json')
        for cell, source, phase in [('base_old', 'base', 'old'), ('base_new', 'base', 'new'), ('gold_new', 'gold', 'new')]:
            budget.charge_tool()
            cells[cell] = probe(factory['images'][phase], directory/source,
                                factory['test_roots'], output/cell, min(90, budget.remaining))
        if not transition_passed(cells):
            raise ValueError('Current artifacts no longer satisfy the three-cell transition gate')
        # Only observed base failure and base source cross the solver boundary.
        factory['attempts'] = [{'cells': {'base_new': cells['base_new']}}]
        config = solver_config(model_config, factory, factory['test_roots'], budget, cap)
        shutil.copytree(directory/'base', output/'solver-repo')
        before = inventory(output/'solver-repo')
        (output/'input-receipt.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
        result = run(config, output/'solver-repo', output/'solver-run', model=model)
        after = inventory(output/'solver-repo')
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        intact = all(after.get(name) == sha for name, sha in factory['frozen_tests'].items())
        passed = result['status'] == 'passed' and bool(changed) and intact
        report.update(status='completed', passed=passed, failure=result.get('failure'),
                      changed_files=changed, frozen_tests_intact=intact, budget=result['budget'],
                      trajectory=trajectory(result, passed), recovery=result.get('recovery'),
                      verification_rounds=len(result.get('verification_attempts', [])))
    except Exception as error:
        report.update(status='error', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        (output/'trial.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factory', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--model-config', required=True, type=Path)
    parser.add_argument('--max-context-bytes', default=24000, type=int)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not 4000 <= args.max_context_bytes <= 128000:
        parser.error('max-context-bytes must be 4000..128000')
    load_factory(args.factory)
    if not args.execute:
        print(json.dumps({'status': 'plan_only', 'next': 'Revalidate environment, then run adaptive Keel repair',
                          'benchmark_ready': False}, indent=2))
        return 0
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
    report = execute(args.factory.resolve(), args.output.resolve(),
                     json.loads(args.model_config.read_text(encoding='utf-8')), args.max_context_bytes)
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
