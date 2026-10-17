"""Collect one explicitly chosen issue/PR pair; no keyword search or inference."""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import canonical_repository_id
from examples.mine_upgradebench import GitHub, unique_file_paths
from keel.evaluation_protocol import file_hash


def collect_pair(fetch, repository, number, issue_repository, issue_number):
    repository = canonical_repository_id(repository)
    issue_repository = canonical_repository_id(issue_repository)
    metadata = fetch('/repos/'+repository)
    resolved = canonical_repository_id(metadata['full_name'])
    pr = fetch(f'/repos/{resolved}/pulls/{number}')
    issue = fetch(f'/repos/{issue_repository}/issues/{issue_number}')
    if pr.get('number') != number or pr.get('merged') is not True:
        raise ValueError('Matching merged PR required')
    if issue.get('number') != issue_number or not isinstance(issue.get('body'), str):
        raise ValueError('Matching issue with report text required')
    revision = pr.get('merge_commit_sha')
    if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Immutable merge revision required')
    commit = fetch(f'/repos/{resolved}/commits/{revision}')
    parents = commit.get('parents', [])
    if commit.get('sha') != revision or not parents or not re.fullmatch('[0-9a-f]{40}', parents[0].get('sha', '')):
        raise ValueError('Verified merge first parent required')
    count = pr.get('changed_files')
    if type(count) is not int or not 1 <= count <= 300:
        raise ValueError('Invalid or unbounded file count')
    entries = []
    for page in range(1, (count+99)//100+1):
        value = fetch(f'/repos/{resolved}/pulls/{number}/files?per_page=100&page={page}')
        if not isinstance(value, list):
            raise ValueError('File page must be a list')
        entries.extend(value)
    files, operations = unique_file_paths(entries, count)
    return {'repository': resolved, 'requested_repository': repository, 'number': number,
            'title': pr.get('title'), 'base_commit': parents[0]['sha'], 'gold_commit': revision,
            'files_curator_only': files, 'file_listing_operations': operations,
            'reported_issue': {'repository': issue_repository, 'number': issue_number,
                               'title': issue.get('title'), 'body': issue['body']},
            'status': 'metadata_collected_needs_source_review', 'model_calls': 0,
            'benchmark_ready': False, 'independent_tasks_ready': 0,
            'limitations': 'Explicit curator-selected pair, not random or representative. Issue/PR relationship, regression-test coverage and reproducible old/new transition remain unverified. Gold metadata is curator-only.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--issue-repository', required=True)
    parser.add_argument('--issue', type=int, required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    repo, issue_repo = canonical_repository_id(args.repository), canonical_repository_id(args.issue_repository)
    if args.pr <= 0 or args.issue <= 0:
        parser.error('Positive issue/PR numbers required')
    args.output.mkdir(parents=True, exist_ok=False)
    plan = {'repository': repo, 'pr': args.pr, 'issue_repository': issue_repo, 'issue': args.issue,
            'runner_sha256': file_hash(Path(__file__)), 'model_calls': 0, 'benchmark_ready': False}
    (args.output/'plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    report = {'status': 'prepared_only', **plan}
    if args.execute:
        api = GitHub(args.output/'responses')
        try:
            report = collect_pair(api.get, repo, args.pr, issue_repo, args.issue)
        except (OSError, ValueError, KeyError, TypeError) as error:
            report.update(status='metadata_error', error=f'{type(error).__name__}: {error}')
    (args.output/'candidate.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 1 if report['status'] == 'metadata_error' else 0


if __name__ == '__main__':
    raise SystemExit(main())
