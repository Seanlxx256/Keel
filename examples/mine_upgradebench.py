"""Read-only bounded GitHub PR collection for UpgradeBench metadata screening."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import canonical_repository_id
from keel.upgradebench import UPGRADE, freeze_candidates, source_file


class MissingCommitError(ValueError):
    """GitHub explicitly reports no object for a requested immutable commit."""


def cached_value(value):
    if isinstance(value, dict) and value.get('_keel_missing_commit') is True:
        raise MissingCommitError('GitHub reports the requested merge commit is unavailable')
    return value


class GitHub:
    def __init__(self, output, *, cached=None):
        self.output, self.receipts = output, []
        self.last_error = None
        self.cached = cached or {}
        output.mkdir(parents=True, exist_ok=False)

    def get(self, route):
        if route in self.cached:
            return cached_value(self._save(route, json.dumps(self.cached[route]).encode('utf-8')))
        for attempt in range(3):
            try:
                return self._get(route)
            except ConnectionError:
                if attempt == 2:
                    raise ValueError('GitHub connection failed after 3 attempts') from None
                print(f'[UpgradeBench] connection retry {attempt + 1}/2', file=sys.stderr, flush=True)
                time.sleep(2 ** attempt)

    def _get(self, route):
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'keel-upgradebench'}
        token = os.environ.get('GITHUB_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request('https://api.github.com' + route, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(10_000_001)
        except urllib.error.HTTPError as error:
            diagnostic = {'http_status': error.code, 'authenticated': bool(token)}
            for header in ('x-ratelimit-limit', 'x-ratelimit-remaining', 'x-ratelimit-reset', 'retry-after'):
                value = error.headers.get(header) if error.headers else None
                if value and re.fullmatch(r'[0-9]{1,12}', value):
                    diagnostic[header] = int(value)
            try:
                body = json.loads(error.read(65_536))
                message = str(body.get('message', '')).lower() if isinstance(body, dict) else ''
            except (ValueError, OSError):
                message = ''
            finally:
                error.close()
            if error.code in (403, 429) and diagnostic.get('x-ratelimit-remaining') == 0:
                category, hint = 'primary_rate_limit', 'Wait until x-ratelimit-reset; authenticated requests may have a separate quota.'
            elif error.code in (403, 429) and ('secondary rate' in message or 'retry-after' in diagnostic):
                category, hint = 'secondary_rate_limit', 'Stop retrying; respect retry-after or GitHub secondary-limit guidance.'
            elif error.code == 401:
                category, hint = 'authentication_failed', 'Check GITHUB_TOKEN locally; never share its value.'
            elif error.code in (404, 422) and re.fullmatch(r'/repos/[^/]+/[^/]+/commits/[0-9a-f]{40}', route) and message.startswith('no commit found for sha:'):
                diagnostic.update(category='merge_commit_unavailable', hint='Preserve candidate exclusion; no commit metadata or parent is verified.')
                self.last_error = diagnostic
                self._save(route, json.dumps({'_keel_missing_commit': True, 'diagnostic': diagnostic}).encode())
                raise MissingCommitError('GitHub reports the requested merge commit is unavailable') from None
            elif error.code == 422:
                category, hint = 'request_validation_failed', 'Check the canonical repository name and search qualifiers; do not retry unchanged.'
            elif 'resource not accessible' in message or 'saml' in message:
                category, hint = 'permission_denied', 'Check token repository access, permissions, and organization authorization.'
            else:
                category, hint = 'http_access_error', 'Cause is unconfirmed; check network/proxy access and GitHub API permissions.'
            diagnostic.update(category=category, hint=hint)
            self.last_error = diagnostic
            raise ValueError(f'GitHub HTTP {error.code}: {category}. {hint}') from None
        except OSError:
            raise ConnectionError('GitHub connection failed') from None
        if len(raw) > 10_000_000:
            raise ValueError('GitHub response exceeds 10 MB')
        return self._save(route, raw)

    def _save(self, route, raw):
        value = json.loads(raw)
        name = f'{len(self.receipts):04d}.json'
        (self.output / name).write_bytes(raw)
        self.receipts.append({'route': route, 'file': name, 'sha256': hashlib.sha256(raw).hexdigest()})
        (self.output.parent / 'receipts.json').write_text(json.dumps(self.receipts, indent=2), encoding='utf-8')
        return value


def replay_fetch(directory):
    """Replay only hash-verified responses; never silently fall back to network."""
    directory = Path(directory)
    receipts = json.loads((directory / 'receipts.json').read_text(encoding='utf-8'))
    routes = {}
    for receipt in receipts:
        name = receipt['file']
        if not re.fullmatch(r'[0-9]+\.json', name):
            raise ValueError('Invalid replay receipt filename')
        raw = (directory / 'responses' / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt['sha256']:
            raise ValueError('Replay response hash mismatch')
        routes[receipt['route']] = json.loads(raw)
    def fetch(route):
        if route not in routes:
            raise ValueError('Offline replay reached an uncached request')
        return cached_value(routes[route])
    fetch.routes = routes
    return fetch


def unique_file_paths(rows, expected):
    groups = {}
    for entry in rows:
        name = entry.get('filename') if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name:
            raise ValueError('Invalid PR file record')
        groups.setdefault(name, []).append(entry)
    duplicates = []
    for name, entries in groups.items():
        if len(entries) > 1:
            if len(entries) != 2 or {e.get('status') for e in entries} != {'added', 'removed'}:
                raise ValueError('Incomplete or duplicate PR file listing')
            duplicates.append({'path': name, 'statuses': ['added', 'removed']})
    if len(groups) != expected:
        raise ValueError('Incomplete or duplicate PR file listing')
    return list(groups), duplicates


def collect(repository, fetch, *, limit=5, pages=1, on_candidate=None,
            discovery='recent', query='migration', on_skip=None, record_missing_commits=False, dependency=None):
    repository = canonical_repository_id(repository)
    if discovery == 'search':
        metadata = fetch('/repos/' + repository)
        resolved = canonical_repository_id(metadata.get('full_name'))
        if resolved != repository:
            print(f'[UpgradeBench] repository resolved: {repository} -> {resolved}', file=sys.stderr, flush=True)
        repository = resolved
    prefix = '/repos/' + repository
    selected, seen = [], set()
    for page in range(1, pages + 1):
        if discovery == 'search':
            params = urlencode({'q': f'repo:{repository} is:pr is:merged {query} in:title',
                                'sort': 'updated', 'order': 'desc', 'per_page': 100, 'page': page})
            result = fetch('/search/issues?' + params)
            if result.get('incomplete_results') is not False:
                raise ValueError('Incomplete GitHub search results')
            rows = result['items']
        else:
            rows = fetch(f'{prefix}/pulls?state=closed&sort=updated&direction=desc&per_page=100&page={page}')
        if not isinstance(rows, list):
            raise ValueError('Invalid pull request listing')
        for row in rows:
            if (discovery == 'recent' and (not row.get('merged_at') or not UPGRADE.search(row.get('title', '')))) or row['number'] in seen:
                continue
            seen.add(row['number'])
            pr = fetch(f"{prefix}/pulls/{row['number']}")
            if pr.get('merged') is not True:
                raise ValueError('Selected PR is not merged')
            signal = None
            if dependency is not None:
                from keel.transition_signal import extract
                signal = extract(pr['title'], pr.get('body'), dependency)
            count = pr.get('changed_files')
            if type(count) is not int or not 0 < count <= 300:
                raise ValueError('Candidate file count is invalid or exceeds the 300-file collection cap')
            file_entries = []
            for file_page in range(1, (count + 99) // 100 + 1):
                file_rows = fetch(f"{prefix}/pulls/{row['number']}/files?per_page=100&page={file_page}")
                if not isinstance(file_rows, list):
                    raise ValueError('Invalid PR file listing')
                file_entries.extend(file_rows)
            files, file_operations = unique_file_paths(file_entries, count)
            if discovery == 'search' and not any(source_file(path) for path in files):
                if on_skip is not None:
                    on_skip({'number': row['number'], 'reason': 'no_non_test_source_change'})
                continue
            gold = pr['merge_commit_sha']
            if not isinstance(gold, str) or not re.fullmatch('[0-9a-f]{40}', gold):
                raise ValueError('Merged revision must be a full commit SHA')
            try:
                commit = fetch(f'{prefix}/commits/{gold}')
            except MissingCommitError:
                if not record_missing_commits:
                    raise
                unresolved = {'repository': repository, 'number': row['number'], 'title': pr['title'],
                    'merged': True, 'base_commit': None, 'gold_commit': gold, 'files': files, 'ci_paths': [],
                    'metadata_error': 'merge_commit_unavailable'}
                if dependency is not None:
                    unresolved['transition_signal'] = signal
                selected.append(unresolved)
                if on_candidate is not None:
                    on_candidate(unresolved)
                if len(selected) == limit:
                    return selected
                continue
            if commit.get('sha') != gold or not commit.get('parents'):
                raise ValueError('Merged commit is missing its verified first parent')
            tree = fetch(f'{prefix}/git/trees/{gold}?recursive=1')
            if tree.get('truncated') is not False:
                raise ValueError('Incomplete CI tree listing')
            ci = [entry['path'] for entry in tree['tree'] if entry.get('type') == 'blob' and
                  (entry['path'].startswith('.github/workflows/') or entry['path'] in {'.gitlab-ci.yml', '.travis.yml', 'Jenkinsfile'})]
            selected.append({'repository': repository, 'number': row['number'], 'title': pr['title'],
                             'merged': pr['merged'], 'base_commit': commit['parents'][0]['sha'],
                             'gold_commit': gold, 'files': files, 'ci_paths': ci,
                             'file_listing_operations': file_operations})
            if dependency is not None:
                selected[-1]['transition_signal'] = signal
            if on_candidate is not None:
                on_candidate(selected[-1])
            print(f"[UpgradeBench] collected {repository}#{row['number']} ({len(files)} files)", file=sys.stderr, flush=True)
            if len(selected) == limit:
                return selected
        if len(rows) < 100:
            break
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True, help='Explicit owner/repository')
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--pages', type=int, default=1)
    parser.add_argument('--replay-from', type=Path, help='Offline recovery from a previous artifact directory')
    parser.add_argument('--resume-from', type=Path, help='Reuse verified responses and fetch missing routes')
    parser.add_argument('--discovery', choices=['recent', 'search'], default='recent')
    parser.add_argument('--query', choices=['migration', 'compatibility', 'upgrade'], default='migration')
    parser.add_argument('--output-dir', type=Path, default=Path('.keel/upgradebench-mining') / uuid.uuid4().hex)
    args = parser.parse_args()
    if not 1 <= args.limit <= 20 or not 1 <= args.pages <= 3:
        parser.error('--limit must be 1..20 and --pages 1..3')
    repo = canonical_repository_id(args.repository)
    if args.replay_from and args.resume_from:
        parser.error('--replay-from and --resume-from are mutually exclusive')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    api = GitHub(output / 'responses')
    print(f'Artifacts: {output}', flush=True)
    summary = {'repository': repo, 'ready_tasks': 0, 'status': 'failed', 'error': None}
    summary.update(discovery=args.discovery, query=args.query if args.discovery == 'search' else None)
    recovered = []
    skipped = []
    def checkpoint(row):
        recovered.append(row)
        with (output / 'collected.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row) + '\n')
    def freeze(rows, complete):
        return freeze_candidates(rows, output / 'screening', provenance={
            'origin': 'GitHub response replay' if args.replay_from else 'GitHub REST API',
            'repository': repo, 'receipts': api.receipts, 'collection_complete': complete,
            'replay_source': str(args.replay_from.resolve()) if args.replay_from else None,
            'resume_source': str(args.resume_from.resolve()) if args.resume_from else None,
            'discovery': args.discovery, 'query': summary['query'],
            'authenticity_verified': False, 'base_rule': 'first parent of merged commit; not the mutable PR base field'})
    try:
        if args.resume_from:
            api.cached = replay_fetch(args.resume_from).routes
        fetch = replay_fetch(args.replay_from) if args.replay_from else api.get
        def skip(row):
            skipped.append(row)
            with (output / 'discovery-skips.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row) + '\n')
        candidates = collect(repo, fetch, limit=args.limit, pages=args.pages, on_candidate=checkpoint,
                             discovery=args.discovery, query=args.query, on_skip=skip)
        report = freeze(candidates, True)
        summary.update(status='screened', counts=report['counts'], triage=report['triage'])
    except (ValueError, KeyError, TypeError, OSError) as error:
        summary['error'] = str(error)
        if recovered and not (output / 'screening').exists():
            report = freeze(recovered, False)
            summary.update(status='partial', counts=report['counts'], triage=report['triage'])
    finally:
        summary['discovery_skipped'] = len(skipped)
        if api.last_error is not None:
            summary['github_error'] = api.last_error
        (output / 'receipts.json').write_text(json.dumps(api.receipts, indent=2), encoding='utf-8')
        (output / 'mining.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if summary['status'] == 'screened' else 1


if __name__ == '__main__':
    raise SystemExit(main())
