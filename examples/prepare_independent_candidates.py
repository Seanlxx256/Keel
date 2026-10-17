"""Collect a policy-bound candidate pool; no Docker, inference or task execution."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.mine_upgradebench import GitHub, collect, replay_fetch
from keel.candidate_selection import shortlist, validate_policy
from keel.evaluation_protocol import registry, file_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, default=Path('examples/independent_candidate_policy.json'))
    parser.add_argument('--execute', action='store_true', help='Read public GitHub metadata only; no paid model calls')
    parser.add_argument('--replay-from', type=Path, help='Offline replay of hash-verified collection receipts')
    parser.add_argument('--resume-from', type=Path, help='Reuse verified cached responses; fetch only missing routes under the same policy')
    parser.add_argument('--cache-from', type=Path, help='New v2 experiment reusing a v1/v2 collection cache; provenance retained')
    parser.add_argument('--file-listing-amendment', action='store_true', help='Explicit new collection using verified prior receipts with changed collector file-operation handling; requires resume-from')
    args = parser.parse_args()
    if args.file_listing_amendment and not args.resume_from:
        parser.error('--file-listing-amendment requires --resume-from')
    if sum(bool(value) for value in (args.execute, args.replay_from, args.resume_from, args.cache_from)) > 1:
        parser.error('Choose only one collection/replay/resume/cache mode')
    root = Path(__file__).resolve().parents[1]
    raw = args.policy.read_bytes()
    policy = json.loads(raw)
    known = registry(root)
    repos = validate_policy(policy, known)
    policy_hash = hashlib.sha256(raw).hexdigest()
    code_hashes = {'collector_sha256': file_hash(root/'examples/mine_upgradebench.py'),
        'selector_sha256': file_hash(root/'keel/candidate_selection.py'),
        'runner_sha256': file_hash(Path(__file__).resolve())}
    if policy['schema_version'] == 3:
        code_hashes['transition_extractor_sha256'] = file_hash(root/'keel/transition_signal.py')
    prior = args.replay_from or args.resume_from or args.cache_from
    if prior:
        original = json.loads((prior/'plan.json').read_text(encoding='utf-8'))
        if original['development_registry_sha256'] != file_hash(root/'examples/evaluation_development_registry.json'):
            raise ValueError('Replay policy or development registry differs')
        if args.cache_from:
            old, new = dict(original['policy']), dict(policy)
            for item in (old, new):
                item.pop('schema_version', None)
                item.pop('missing_commit_policy', None)
            if policy['schema_version'] != 2 or old != new:
                raise ValueError('Cache reuse permits only the explicit v2 missing-commit amendment, not changed search or sampling')
        else:
            if original['policy_sha256'] != policy_hash:
                raise ValueError('Replay policy differs')
            required_hashes = code_hashes if args.replay_from else {key: value for key, value in code_hashes.items() if key != 'runner_sha256'}
            if args.file_listing_amendment:
                required_hashes = {key: value for key, value in required_hashes.items() if key != 'collector_sha256'}
            if any(original.get(key) != value for key, value in required_hashes.items()):
                raise ValueError('Replay collector/selection implementation differs')
    output = root/'.keel/independent-candidates'/uuid.uuid4().hex
    output.mkdir(parents=True)
    print(f'Artifacts: {output}', flush=True)
    plan = {'policy': policy, 'policy_sha256': policy_hash,
        'development_registry_sha256': file_hash(root/'examples/evaluation_development_registry.json'),
        **code_hashes, 'benchmark_ready': False}
    if args.file_listing_amendment:
        plan['collector_amendment'] = 'unique-path-added-removed-pair-v1; raw receipts retained; policy and selector unchanged; new collection'
    if prior:
        plan['prior_collection'] = {'directory': str(prior.resolve()), 'mode': 'new_v2_cache_reuse' if args.cache_from else 'resume' if args.resume_from else 'offline_replay',
            'plan_sha256': file_hash(prior/'plan.json'), 'previous_runner_sha256': original.get('runner_sha256'),
            'previous_collector_sha256': original.get('collector_sha256'), 'previous_selector_sha256': original.get('selector_sha256'),
            'scope': 'New experiment with explicit missing-commit amendment; original result unchanged' if args.cache_from else 'Policy, registry, collector and selector unchanged; resume records runner changes explicitly'}
    (output/'plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    collections = {repo: {'status': 'prepared', 'candidates': [], 'skipped': []} for repo in repos}
    def save():
        result = shortlist(policy, known, collections)
        (output/'collections.json').write_text(json.dumps(collections, indent=2), encoding='utf-8')
        (output/'shortlist.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    result = save()
    active = bool(args.execute or prior)
    if active:
        for number, repo in enumerate(repos, 1):
            print(f'[Candidates {number}/{len(repos)}] {repo}', flush=True)
            directory = output/'repositories'/repo.replace('/', '--')
            directory.mkdir(parents=True)
            state = collections[repo]
            client = None
            route = None
            try:
                if args.replay_from:
                    source = args.replay_from/'repositories'/repo.replace('/', '--')
                    fetch = replay_fetch(source)
                    shutil.copytree(source/'responses', directory/'responses')
                    shutil.copyfile(source/'receipts.json', directory/'receipts.json')
                else:
                    cache = args.resume_from or args.cache_from
                    cached = replay_fetch(cache/'repositories'/repo.replace('/', '--')).routes if cache else None
                    client = GitHub(directory/'responses', cached=cached) if cached is not None else GitHub(directory/'responses')
                    fetch = client.get
                def tracked_fetch(request_route):
                    nonlocal route
                    route = request_route
                    return fetch(request_route)
                def retain(row):
                    state['candidates'].append(row)
                    save()
                dependency = policy['dependencies'][repo] if policy['schema_version'] == 3 else None
                collect(repo, tracked_fetch, limit=policy['limit_per_repository'], pages=policy['pages'],
                    discovery='search', query=dependency or policy['query'], dependency=dependency, on_candidate=retain,
                    record_missing_commits=policy.get('missing_commit_policy') == 'record_exclusion_count_toward_limit',
                    on_skip=lambda row: state['skipped'].append(row))
                state['status'] = 'completed'
            except (OSError, ValueError, KeyError, TypeError) as error:
                state.update(status='failed', error=f'{type(error).__name__}: {error}')
                if route is not None:
                    state['failed_route'] = route
                if client and client.last_error:
                    state['github_error'] = client.last_error
            result = save()
    print(json.dumps({'prepared_only': not active, 'status': result['status'], 'collection_complete': result['collection_complete'],
        'policy_version': policy['schema_version'],
        'repositories': [{'repository': repo, 'status': state['status'], 'collected': len(state['candidates']),
            'skipped': len(state['skipped']), 'error': state.get('error'), 'failed_route': state.get('failed_route')}
            for repo, state in collections.items()],
        'selected': result['selected'], 'independent_tasks_ready': 0, 'benchmark_ready': False}, indent=2))
    return 0 if not active or result['status'] == 'shortlisted' else 1


if __name__ == '__main__':
    raise SystemExit(main())
