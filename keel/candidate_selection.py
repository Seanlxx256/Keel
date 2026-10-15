"""Outcome-blind, bounded candidate shortlist; not executable benchmark tasks."""
import hashlib
import re

from .evaluation_protocol import canonical_repo
from .upgradebench import source_file, classify_candidate


def validate_policy(policy, known):
    expected = {'schema_version', 'repositories', 'query', 'limit_per_repository', 'pages', 'seed',
        'selected_repositories', 'max_changed_python_sources', 'localization_policy', 'attempt_policy', 'scope'}
    if isinstance(policy, dict) and policy.get('schema_version') in (2, 3):
        expected.add('missing_commit_policy')
    if isinstance(policy, dict) and policy.get('schema_version') == 3:
        expected.add('dependencies')
    if not isinstance(policy, dict) or set(policy) != expected or policy['schema_version'] not in (1, 2, 3):
        raise ValueError('Unsupported or incomplete candidate policy')
    if policy['schema_version'] in (2, 3) and policy['missing_commit_policy'] != 'record_exclusion_count_toward_limit':
        raise ValueError('Unsupported missing-commit handling')
    repos = policy['repositories']
    if not isinstance(repos, list) or not 1 <= len(repos) <= 10:
        raise ValueError('Require 1..10 repositories')
    normalized = [canonical_repo(value, known) for value in repos]
    dev = {canonical_repo(row['repository'], known) for row in known['tasks']}
    if len(set(normalized)) != len(normalized) or set(normalized) & dev:
        raise ValueError('Duplicate or development repository in policy')
    for key, low, high in [('limit_per_repository', 1, 10), ('pages', 1, 3),
                           ('selected_repositories', 1, len(repos)), ('max_changed_python_sources', 1, 8)]:
        if type(policy[key]) is not int or not low <= policy[key] <= high:
            raise ValueError('Invalid bounded policy field: ' + key)
    if type(policy['seed']) is not int or policy['query'] != ('dependency-name' if policy['schema_version'] == 3 else 'compatibility'):
        raise ValueError('Integer seed and fixed compatibility query required')
    if policy['schema_version'] == 3:
        deps = policy['dependencies']
        if not isinstance(deps, dict) or set(deps) != set(normalized) or any(
                not isinstance(value, str) or not re.fullmatch('[a-z][a-z0-9_-]{0,49}', value) for value in deps.values()):
            raise ValueError('One explicit dependency name per canonical repository required')
    return normalized


def shortlist(policy, known, collections):
    repos = validate_policy(policy, known)
    if set(collections) != set(repos):
        raise ValueError('Every planned repository must have a collection record')
    screened, seen = [], set()
    for planned in repos:
        collection = collections[planned]
        for row in collection['candidates']:
            repo = canonical_repo(row['repository'], known)
            number = row['number']
            if repo != planned or type(number) is not int or number <= 0 or (repo, number) in seen:
                raise ValueError('Repository mismatch or repeated candidate')
            seen.add((repo, number))
            reasons = []
            if row.get('metadata_error') == 'merge_commit_unavailable':
                reasons.append('merge_commit_unavailable')
            files = row['files']
            if not isinstance(files, list) or not files or any(not isinstance(name, str) for name in files) or len(set(files)) != len(files):
                raise ValueError('Complete unique file list required')
            sources = sorted(path for path in files if source_file(path))
            if row.get('merged') is not True:
                reasons.append('not_merged')
            if policy['schema_version'] == 3:
                from .transition_signal import extract
                signal = row.get('transition_signal')
                dependency = policy['dependencies'][repo]
                if not isinstance(signal, dict) or signal.get('dependency') != dependency or not extract(signal.get('excerpt'), '', dependency):
                    reasons.append('no_dependency_version_evidence')
            elif not re.search(r'\bcompatib\w*', row['title'], re.I):
                reasons.append('no_compatibility_title')
            if classify_candidate(row['title'], files)['category'] != 'unclassified_upgrade':
                reasons.append('tooling_or_ci')
            if not 1 <= len(sources) <= policy['max_changed_python_sources']:
                reasons.append('source_count_outside_policy')
            if any(not path.endswith('.py') for path in sources):
                reasons.append('non_python_source')
            if any(not isinstance(row.get(key), str) or not re.fullmatch('[0-9a-f]{40}', row[key]) for key in ('base_commit', 'gold_commit')):
                reasons.append('unpinned_revisions')
            rank = hashlib.sha256(f"{policy['seed']}:{repo}:{number}".encode()).hexdigest()
            screened.append({'repository': repo, 'number': number, 'title': row['title'],
                'eligible_metadata_only': not reasons, 'reasons': reasons, 'rank': rank,
                'base_commit': row.get('base_commit'), 'gold_commit': row.get('gold_commit'),
                'source_files_curator_only': sources})
            if policy['schema_version'] == 3:
                screened[-1]['transition_signal'] = row.get('transition_signal')
    complete = all(row['status'] == 'completed' for row in collections.values())
    eligible = [row for row in screened if row['eligible_metadata_only']]
    winners = []
    for repo in repos:
        rows = sorted((row for row in eligible if row['repository'] == repo), key=lambda row: row['rank'])
        if rows:
            winners.append(rows[0])
    winners.sort(key=lambda row: hashlib.sha256(f"{policy['seed']}:{row['repository']}".encode()).hexdigest())
    sufficient = len(winners) >= policy['selected_repositories']
    return {'collection_complete': complete, 'sufficient_repositories': sufficient,
        'screened': sorted(screened, key=lambda row: (row['repository'], row['number'])),
        'selected': winners[:policy['selected_repositories']] if complete and sufficient else [],
        'status': 'shortlisted' if complete and sufficient else 'incomplete' if not complete else 'insufficient_candidates',
        'benchmark_ready': False, 'independent_tasks_ready': 0,
        'limitations': 'Metadata-only shortlist within bounded updated-order search. No model runs, reproduction validation, independent score, or automatic replacement of later failures.'}
