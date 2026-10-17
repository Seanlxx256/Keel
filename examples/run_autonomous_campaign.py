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
from keel.task_factory import EnvironmentPlanner, construct, inventory, automatic_acceptance_supported, unsupported_transition
from keel.evaluation_protocol import implementation_hashes
from keel.campaign_reporting import FrozenModel, trajectory


class RepositorySearchLimit(ValueError):
    """One repository must not consume the entire campaign discovery budget."""


def discover(fetch, count, excluded=()):
    requested = min(100, count + len(set(excluded)))
    params = urlencode({'q': 'language:Python stars:>1000 archived:false topic:python-library', 'sort': 'stars',
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
    target = ('Python ' if factory['recipe'].get('kind') == 'python' else '') + factory['recipe']['new']
    goal = (factory['candidate']['title'] + '\nRestore compatibility with ' + target +
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
             environment_attempts=3, cap=24000, limits=None, reuse_candidate=None):
    archived = None
    if reuse_candidate is not None:
        reuse_candidate = reuse_candidate.resolve()
        if repositories is not None or output.resolve().is_relative_to(reuse_candidate):
            raise ValueError('Reuse requires no repository filter and an output outside the archived candidate')
        archived = json.loads((reuse_candidate/'factory/factory.json').read_text(encoding='utf-8'))
        repositories = [archived['candidate']['repository']]
    output.mkdir(parents=True, exist_ok=False)
    model = from_config(model_config)
    budget = Budget(limits or Limits(max_wallclock=1800, max_model_calls=30, max_tokens=300000, max_tool_calls=100))
    report = {'status': 'running', 'repositories': [], 'records': [], 'benchmark_ready': False,
              'implementation': implementation_hashes(root),
              'scope': 'Exploratory automatic collection; repository overlap/selection bias not independently reviewed.'}
    report['settings'] = {'repository_limit': repository_limit, 'candidates_per_repo': candidates_per_repo,
                          'environment_attempts': environment_attempts, 'max_context_bytes': cap}
    if archived is not None:
        from keel.evaluation_protocol import file_hash
        report['retry_from'] = {'directory': str(reuse_candidate),
                                'factory_sha256': file_hash(reuse_candidate/'factory/factory.json'),
                                'scope': 'New attempt with fresh budget; previous attempt retained, not a first-attempt score'}
    def check_frozen():
        if implementation_hashes(root) != report['implementation']:
            raise ModelError('Frozen campaign implementation changed; start a new campaign, original records retained')
    model = FrozenModel(model, check_frozen)
    def save():
        report['budget'] = budget.report()
        report['counts'] = {'records': len(report['records']),
            'transitions_verified': sum(row.get('factory_status') == 'transition_verified' for row in report['records']),
            'repairs_passed': sum(row.get('passed') is True for row in report['records']),
            'unresolved_or_failed': sum(row.get('passed') is not True for row in report['records'])}
        report['trajectories'] = {name: sum(row.get('trajectory') == name for row in report['records']) for name in
            ('first_verification_pass', 'pre_verification_recovery_pass', 'verification_recovery_pass',
             'replanning_recovery_pass', 'unclassified_pass', 'failed')}
        (output/'campaign.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    api = GitHub(output/'responses')
    try:
        explicit_repositories = repositories is not None
        if repositories is None:
            from keel.evaluation_protocol import registry, canonical_repo
            known = registry(root)
            excluded = {canonical_repo(row['repository'], known) for row in known['tasks']}
            budget.charge_tool()
            repositories = discover(api.get, min(20, max(6, repository_limit * 3)), excluded)
            report['excluded_development_repositories'] = sorted(excluded)
        report['discovered_repositories'] = repositories
        report['repositories'] = []
        report['repository_results'] = []
        admitted = 0
        runnable_repositories = set()
        save()
        for repo_index, repository in enumerate(repositories, 1):
            if not explicit_repositories and len(runnable_repositories) >= repository_limit:
                break
            check_frozen()
            budget.check()
            report['repositories'].append(repository)
            repo_record = {'repository': repository, 'status': 'collecting', 'eligible_candidates': 0, 'excluded_prerequisites': 0}
            report['repository_results'].append(repo_record)
            print(f'[Campaign] repository {repo_index}/{len(repositories)}: {repository}', flush=True)
            try:
                repository_requests = 0
                def fetch(route):
                    nonlocal repository_requests
                    if repository_requests >= 16:
                        raise RepositorySearchLimit('Per-repository metadata search limit reached (16 requests)')
                    repository_requests += 1
                    budget.charge_tool()
                    return api.get(route)
                candidates = []
                excluded_numbers = set()
                def retain(candidate):
                    candidates.append(candidate)
                    with (output/f'collected-repo-{repo_index}.jsonl').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(candidate) + '\n')
                def skip(row):
                    if row['number'] in excluded_numbers:
                        return
                    excluded_numbers.add(row['number'])
                    repo_record['excluded_prerequisites'] += 1
                    with (output/f'exclusions-repo-{repo_index}.jsonl').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(row) + '\n')
                if archived is not None:
                    retain(archived['candidate'])
                else:
                    seen_numbers = set()
                    repo_record['queries'] = []
                    for query in ('compatibility', 'migration', 'upgrade'):
                        if len(candidates) >= candidates_per_repo:
                            break
                        repo_record['queries'].append(query)
                        collect(repository, fetch, limit=candidates_per_repo-len(candidates), pages=1,
                                discovery='search', query=query, seen_numbers=seen_numbers,
                                record_missing_commits=True, on_candidate=retain, on_skip=skip,
                                file_predicate=automatic_acceptance_supported,
                                candidate_predicate=lambda pr: unsupported_transition(pr['title']) is None)
                repo_record.update(status='eligible_candidates' if candidates else 'no_eligible_candidates', eligible_candidates=len(candidates))
                if candidates:
                    admitted += 1
            except RepositorySearchLimit as error:
                repo_record.update(status='search_limit', error=str(error), eligible_candidates=len(candidates))
                if candidates:
                    admitted += 1
                save()
            except (OSError, ValueError) as error:
                repo_record.update(status='collection_error', error=str(error))
                report['records'].append({'repository': repository, 'status': 'collection_error', 'error': str(error)})
                save()
                continue
            save()
            for index, candidate in enumerate(candidates, 1):
                check_frozen()
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
                        snapshot_path = (reuse_candidate if archived is not None else directory)/('snapshot-'+phase)
                        snapshots[phase] = prepare_snapshot(candidate['repository'], commit, snapshot_path,
                                                            offline=archived is not None, timeout=min(120, budget.remaining))
                    planner = EnvironmentPlanner(model, directory, budget)
                    initial = None
                    if archived is not None and archived.get('attempts'):
                        last = archived['attempts'][-1]
                        initial = {'previous_recipe': last.get('recipe'), 'error': last.get('error'),
                                   'builds': {phase: {'returncode': build.get('returncode'),
                                                      'tail': build.get('tail', '')[-3000:]}
                                              for phase, build in last.get('builds', {}).items()},
                                   'scope': 'Observed prior attempt; correct failures without changing acceptance'}
                    factory, workspaces = construct(candidate, snapshots['base'], snapshots['gold'], directory/'factory',
                                                     planner, attempts=environment_attempts, initial_observation=initial)
                    record['factory_status'] = factory['status']
                    record['environment_attempts'] = [{key: attempt.get(key) for key in ('attempt', 'stage', 'status', 'error', 'reason')}
                                                      for attempt in factory.get('attempts', [])]
                    if factory['status'] != 'transition_verified':
                        record['status'] = factory['status'] if factory['status'] in {'unsupported_transition', 'acceptance_review_required'} else 'environment_unresolved'
                        if factory.get('reason'):
                            record['reason'] = factory['reason']
                        continue
                    if budget.model_calls >= budget.limits.max_model_calls:
                        raise BudgetExceeded('Campaign model-call budget exhausted before solver')
                    runnable_repositories.add(repository)
                    config = solver_config(model_config, factory, factory['test_roots'], budget, cap)
                    # Solver only sees a separate base workspace with frozen tests.
                    shutil.copytree(workspaces['base'], directory/'solver-repo')
                    before = inventory(directory/'solver-repo')
                    result = run(config, directory/'solver-repo', directory/'solver-run', model=model)
                    budget.model_calls += result['budget']['model_calls']
                    budget.tool_calls += result['budget']['tool_calls']
                    budget.charge_tokens(result['budget']['tokens'])
                    after = inventory(directory/'solver-repo')
                    check_frozen()
                    changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
                    frozen = factory['frozen_tests']
                    frozen_intact = all(after.get(name) == sha for name, sha in frozen.items())
                    record.update(status='completed', runtime_status=result['status'], failure=result.get('failure'),
                                  changed_files=changed, recovery=result.get('recovery'), frozen_tests_intact=frozen_intact,
                                  passed=result['status'] == 'passed' and bool(changed) and frozen_intact)
                    record['trajectory'] = trajectory(result, record['passed'])
                    record['verification_rounds'] = len(result.get('verification_attempts', []))
                    record['recovery_decisions'] = result.get('recovery_decisions', [])
                except (BudgetExceeded, ModelError) as error:
                    record.update(status='stopped', error=f'{type(error).__name__}: {error}')
                    raise
                except (OSError, ValueError, KeyError, TypeError) as error:
                    record.update(status='candidate_error', error=f'{type(error).__name__}: {error}')
                finally:
                    save()
        completed_solvers = sum(row.get('status') == 'completed' for row in report['records'])
        report['status'] = 'completed' if completed_solvers else 'no_runnable_tasks'
        report['collection_finished'] = True
        report['eligible_repositories'] = admitted
        report['runnable_repositories'] = sorted(runnable_repositories)
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
    parser.add_argument('--reuse-candidate', type=Path, help='Retry an archived candidate using clean local snapshots and previous failure evidence')
    parser.add_argument('--repository-limit', type=int, default=2)
    parser.add_argument('--candidates-per-repo', type=int, default=2)
    parser.add_argument('--environment-attempts', type=int, default=3)
    parser.add_argument('--max-context-bytes', type=int, default=24000)
    parser.add_argument('--execute', action='store_true', help='Run network discovery, Docker builds and metered model calls')
    args = parser.parse_args()
    if args.reuse_candidate and args.repository:
        parser.error('--reuse-candidate cannot be combined with --repository')
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
            'reuse_candidate': str(args.reuse_candidate) if args.reuse_candidate else None,
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
                      cap=args.max_context_bytes, reuse_candidate=args.reuse_candidate)
    # Full immutable implementation inventory remains in campaign.json.
    print(json.dumps({key: value for key, value in report.items() if key != 'implementation'}, indent=2))
    return 0 if report['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
