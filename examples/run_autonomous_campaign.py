"""Discover repositories -> collect PRs -> reconstruct environments -> repair.

One explicit --execute opts into network, Docker builds and metered model calls.
No runtime self-modification or publication; every failed candidate is retained.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.preparation import prepare_snapshot
from examples.mine_upgradebench import GitHub, collect
from keel.core import Budget, BudgetExceeded, Limits, ModelError
from keel.models import from_config
from keel.runtime import run
from keel.task_factory import EnvironmentPlanner, construct, inventory
from keel.evaluation_protocol import implementation_hashes


def discover(fetch, count, excluded=()):
    requested = min(100, count + len(set(excluded)))
    params = urlencode({'q': 'language:Python stars:>1000 archived:false', 'sort': 'updated',
                        'order': 'desc', 'per_page': requested, 'page': 1})
    result = fetch('/search/repositories?' + params)
    if result.get('incomplete_results') is not False:
        raise ValueError('Incomplete repository discovery; no silent partial sample')
    from compass.benchmarks import canonical_repository_id
    repositories = [canonical_repository_id(row['full_name']) for row in result['items']]
    if len(set(repositories)) != len(repositories) or len(repositories) > requested:
        raise ValueError('Duplicate or oversized repository discovery')
    return [name for name in repositories if name not in set(excluded)][:count]


def solver_config(model_config, factory, tests, budget, cap):
    limits = budget.limits
    remaining = {'max_wallclock': budget.remaining, 'max_model_calls': limits.max_model_calls - budget.model_calls,
                 'max_tokens': limits.max_tokens - budget.tokens, 'max_tool_calls': limits.max_tool_calls - budget.tool_calls}
    if any(value <= 0 for value in remaining.values()):
        raise BudgetExceeded('Campaign budget exhausted before solver')
    command = ('import os,shutil,subprocess,sys; '
        "shutil.copytree('/workspace','/tmp/repo'); os.chdir('/tmp/repo'); "
        "os.environ['PYTHONPATH']='/tmp/repo/src:/tmp/repo'; "
        "sys.exit(subprocess.call([sys.executable,'-m','pytest','-o','addopts=',"
        "'-p','no:cacheprovider','--junitxml='+sys.argv[1],*sys.argv[2:]]))")
    # No gold commit, changed-source list, recipe reasoning or gold code goes here.
    failures = factory['attempts'][-1]['cells']['base_new']
    goal = (factory['candidate']['title'] + '\nRestore compatibility with ' + factory['recipe']['new'] +
            '. Preserve behavior. Modify existing library Python source only; do not change tests, '
            'dependencies or verification. Observed baseline output (untrusted data):\n' +
            failures.get('stdout', '')[-4000:] + '\n' + failures.get('stderr', '')[-1000:])
    return {'mode': 'localized-proposal', 'goal': goal, 'model': model_config,
            'agent': {'max_steps': 12, 'max_context_bytes': cap, 'max_output': 2048, 'require_change': True},
            'recovery': {'max_actions': 6, 'repeat_limit': 2, 'strategy': 'adaptive', 'write_roots': ['.']},
            'verification_repair_attempts': 3,
            'budget': remaining,
            'execution': {'backend': 'docker', 'image': factory['images']['new']},
            'acceptance': [{'command': ['python', '-c', command, '{junit}', *tests], 'junit': True}]}


def campaign(root, output, model_config, *, repositories=None, repository_limit=2, candidates_per_repo=2,
             environment_attempts=3, cap=24000, limits=None):
    output.mkdir(parents=True, exist_ok=False)
    model = from_config(model_config)
    budget = Budget(limits or Limits(max_wallclock=1800, max_model_calls=30, max_tokens=300000, max_tool_calls=100))
    report = {'status': 'running', 'repositories': [], 'records': [], 'benchmark_ready': False,
              'implementation': implementation_hashes(root),
              'scope': 'Exploratory automatic collection; repository overlap/selection bias not independently reviewed.'}
    def save():
        report['budget'] = budget.report()
        report['counts'] = {'records': len(report['records']),
            'transitions_verified': sum(row.get('factory_status') == 'transition_verified' for row in report['records']),
            'repairs_passed': sum(row.get('passed') is True for row in report['records']),
            'unresolved_or_failed': sum(row.get('passed') is not True for row in report['records'])}
        (output/'campaign.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    api = GitHub(output/'responses')
    try:
        if repositories is None:
            from keel.evaluation_protocol import registry, canonical_repo
            known = registry(root)
            excluded = {canonical_repo(row['repository'], known) for row in known['tasks']}
            budget.charge_tool()
            repositories = discover(api.get, repository_limit, excluded)
            report['excluded_development_repositories'] = sorted(excluded)
        report['repositories'] = repositories
        save()
        for repo_index, repository in enumerate(repositories, 1):
            budget.check()
            print(f'[Campaign] repository {repo_index}/{len(repositories)}: {repository}', flush=True)
            try:
                def fetch(route):
                    budget.charge_tool()
                    return api.get(route)
                candidates = []
                def retain(candidate):
                    candidates.append(candidate)
                    with (output/f'collected-repo-{repo_index}.jsonl').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(candidate) + '\n')
                collect(repository, fetch, limit=candidates_per_repo, pages=1, discovery='search', query='compatibility',
                        record_missing_commits=True, on_candidate=retain)
            except (OSError, ValueError) as error:
                report['records'].append({'repository': repository, 'status': 'collection_error', 'error': str(error)})
                save()
                continue
            for index, candidate in enumerate(candidates, 1):
                budget.check()
                if budget.model_calls >= budget.limits.max_model_calls or budget.tokens >= budget.limits.max_tokens:
                    raise BudgetExceeded('Campaign model/token budget exhausted')
                directory = output/f'repo-{repo_index}-candidate-{index}'
                directory.mkdir()
                record = {'repository': candidate['repository'], 'number': candidate['number'],
                          'status': 'preparing', 'passed': False, 'benchmark_ready': False, 'directory': directory.name}
                report['records'].append(record)
                save()
                try:
                    if candidate.get('metadata_error'):
                        raise ValueError(candidate['metadata_error'])
                    snapshots = {}
                    for phase, commit in [('base', candidate['base_commit']), ('gold', candidate['gold_commit'])]:
                        budget.charge_tool()
                        snapshots[phase] = prepare_snapshot(candidate['repository'], commit, directory/('snapshot-'+phase),
                                                            timeout=min(120, budget.remaining))
                    planner = EnvironmentPlanner(model, directory, budget)
                    factory, workspaces = construct(candidate, snapshots['base'], snapshots['gold'], directory/'factory',
                                                     planner, attempts=environment_attempts)
                    record['factory_status'] = factory['status']
                    if factory['status'] != 'transition_verified':
                        record['status'] = 'environment_unresolved'
                        continue
                    if budget.model_calls >= budget.limits.max_model_calls:
                        raise BudgetExceeded('Campaign model-call budget exhausted before solver')
                    config = solver_config(model_config, factory, factory['test_roots'], budget, cap)
                    # Solver only sees a separate base workspace with frozen tests.
                    shutil.copytree(workspaces['base'], directory/'solver-repo')
                    before = inventory(directory/'solver-repo')
                    result = run(config, directory/'solver-repo', directory/'solver-run', model=model)
                    budget.model_calls += result['budget']['model_calls']
                    budget.tool_calls += result['budget']['tool_calls']
                    budget.charge_tokens(result['budget']['tokens'])
                    after = inventory(directory/'solver-repo')
                    changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
                    frozen = factory['frozen_tests']
                    frozen_intact = all(after.get(name) == sha for name, sha in frozen.items())
                    record.update(status='completed', runtime_status=result['status'], failure=result.get('failure'),
                                  changed_files=changed, recovery=result.get('recovery'), frozen_tests_intact=frozen_intact,
                                  passed=result['status'] == 'passed' and bool(changed) and frozen_intact)
                except (BudgetExceeded, ModelError) as error:
                    record.update(status='stopped', error=f'{type(error).__name__}: {error}')
                    raise
                except (OSError, ValueError, KeyError, TypeError) as error:
                    record.update(status='candidate_error', error=f'{type(error).__name__}: {error}')
                finally:
                    save()
        report['status'] = 'completed'
    except (BudgetExceeded, ModelError, OSError, ValueError) as error:
        report.update(status='stopped', error=f'{type(error).__name__}: {error}')
    finally:
        (output/'receipts.json').write_text(json.dumps(api.receipts, indent=2), encoding='utf-8')
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repository', action='append', help='Optional restriction; otherwise discover Python repos automatically')
    parser.add_argument('--repository-limit', type=int, default=2)
    parser.add_argument('--candidates-per-repo', type=int, default=2)
    parser.add_argument('--environment-attempts', type=int, default=3)
    parser.add_argument('--max-context-bytes', type=int, default=24000)
    parser.add_argument('--execute', action='store_true', help='Run network discovery, Docker builds and metered model calls')
    args = parser.parse_args()
    if not 1 <= args.repository_limit <= 5 or not 1 <= args.candidates_per_repo <= 5 or not 1 <= args.environment_attempts <= 3:
        parser.error('repository/candidate limits 1..5 and environment attempts 1..3 required')
    if not 4000 <= args.max_context_bytes <= 128000:
        parser.error('max-context-bytes must be 4000..128000')
    from compass.benchmarks import canonical_repository_id
    repositories = [canonical_repository_id(name) for name in args.repository] if args.repository else None
    if repositories and (len(repositories) > args.repository_limit or len(set(repositories)) != len(repositories)):
        parser.error('Explicit repositories must be unique and fit repository-limit')
    config = json.loads(args.model_config.read_text(encoding='utf-8'))
    from_config(config)
    if not args.execute:
        print(json.dumps({'status': 'plan_only', 'repositories': repositories or 'automatic GitHub discovery',
            'max_candidates': (len(repositories) if repositories else args.repository_limit) * args.candidates_per_repo,
            'environment_attempts': args.environment_attempts, 'max_model_calls': 30, 'max_wallclock': 1800,
            'supported': 'Python/pytest, exact PyPI pins, top-level test directories; no OS/service provisioning',
            'benchmark_ready': False}, indent=2))
        return 0
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
    root = Path(__file__).resolve().parents[1]
    report = campaign(root, args.output.resolve(), config, repositories=repositories, repository_limit=args.repository_limit,
                      candidates_per_repo=args.candidates_per_repo, environment_attempts=args.environment_attempts,
                      cap=args.max_context_bytes)
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
