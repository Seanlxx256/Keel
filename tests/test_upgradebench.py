import copy
import json
import io
import hashlib
import os
import urllib.error
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

from keel.upgradebench import freeze_candidates, screen
from examples.mine_upgradebench import GitHub, collect, main, replay_fetch


def candidate(number=1):
    return {'repository': 'Org/Repo', 'number': number, 'title': 'Upgrade library to version 2',
            'merged': True, 'base_commit': 'a' * 40, 'gold_commit': 'b' * 40,
            'files': ['pyproject.toml', 'src/app.py', 'tests/test_app.py'],
            'ci_paths': ['.github/workflows/test.yml']}


class UpgradeBenchTests(unittest.TestCase):
    def test_compatibility_pool_preserves_strict_rejection_and_requires_full_review(self):
        row = {**candidate(), 'title': 'Add compatibility with next AnyIO',
               'files': ['src/client.py']}
        result = screen(row)
        self.assertFalse(result['eligible_candidate'])
        self.assertFalse(result['main_track_candidate'])
        self.assertTrue(result['compatibility_review_candidate'])
        self.assertFalse(result['benchmark_ready'])
        self.assertEqual(set(result['reasons']), {'fewer_than_three_changed_files', 'no_dependency_manifest_change'})
        for changes in [{'merged': False}, {'ci_paths': []}, {'files': ['tests/test_client.py']},
                        {'title': 'Upgrade ruff compatibility'}, {'title': 'Bump version'}]:
            with self.subTest(changes=changes):
                self.assertFalse(screen({**row, **changes})['compatibility_review_candidate'])
        with tempfile.TemporaryDirectory() as directory:
            report = freeze_candidates([row], Path(directory)/'out')
            self.assertEqual(report['counts']['eligible'], 0)
            self.assertEqual(report['triage']['compatibility_review_candidates'], 1)
            self.assertEqual(report['compatibility_review_queue']['ids'], ['org__repo-1'])
            self.assertEqual(report['compatibility_review_queue']['review_fraction'], 1.0)

    def test_connection_retries_are_bounded_and_cache_resume_avoids_network(self):
        with tempfile.TemporaryDirectory() as directory:
            api = GitHub(Path(directory) / 'responses')
            with patch('urllib.request.urlopen', side_effect=OSError('secret')), patch(
                    'examples.mine_upgradebench.time.sleep') as sleep:
                with self.assertRaisesRegex(ValueError, '3 attempts'):
                    api.get('/test')
                self.assertEqual(sleep.call_count, 2)
            api.cached = {'/test': []}
            with patch('urllib.request.urlopen') as network:
                self.assertEqual(api.get('/test'), [])
                network.assert_not_called()
            self.assertEqual(replay_fetch(Path(directory))('/test'), [])

    def test_search_rejects_incomplete_results_and_skips_before_commit_fetch(self):
        calls, skipped = [], []
        def fetch(route):
            calls.append(route)
            if route == '/repos/org/repo':
                return {'full_name': 'org/repo'}
            if route.startswith('/search/issues?'):
                self.assertIn('is%3Amerged', route)
                self.assertIn('compatibility', route)
                return {'incomplete_results': False, 'items': [{'number': 1}]}
            if '/files?' in route:
                return [{'filename': 'requirements.txt'}]
            if '/pulls/1' in route:
                return {'merged': True, 'changed_files': 1}
            self.fail('Commit and CI tree should not be requested for excluded PR')
        self.assertEqual(collect('org/repo', fetch, discovery='search', query='compatibility', on_skip=skipped.append), [])
        self.assertEqual(skipped, [{'number': 1, 'reason': 'no_non_test_source_change'}])
        with self.assertRaisesRegex(ValueError, 'Incomplete GitHub search'):
            collect('org/repo', lambda route: {'full_name': 'org/repo'} if route == '/repos/org/repo'
                    else {'incomplete_results': True}, discovery='search')

    def test_search_resolves_transferred_repository_before_query(self):
        calls = []
        def fetch(route):
            calls.append(route)
            if route == '/repos/old/project':
                return {'full_name': 'New/project'}
            self.assertIn('repo%3Anew%2Fproject', route)
            self.assertNotIn('repo%3Aold', route)
            return {'incomplete_results': False, 'items': []}
        self.assertEqual(collect('old/project', fetch, discovery='search'), [])
        self.assertEqual(len(calls), 2)

    def test_tooling_is_separated_without_claiming_runtime_compatibility(self):
        for title, expected in [('Upgrade Python formatter ruff', 'developer_tooling'),
                                ('Bump actions/checkout to v5', 'ci_tooling'),
                                ('Upgrade library to version 2', 'unclassified_upgrade')]:
            with self.subTest(title=title):
                record = screen({**candidate(), 'title': title})
                self.assertTrue(record['eligible_candidate'])
                self.assertEqual(record['classification']['category'], expected)
                self.assertEqual(record['main_track_candidate'], expected == 'unclassified_upgrade')
                self.assertFalse(record['classification']['runtime_compatibility_verified'])
                self.assertFalse(record['benchmark_ready'])
        workflow = screen({**candidate(), 'files': ['.github/workflows/check.yml']})
        self.assertEqual(workflow['classification']['category'], 'ci_tooling')
        with tempfile.TemporaryDirectory() as directory:
            report = freeze_candidates([candidate(), {**candidate(2), 'title': 'Upgrade ruff'}], Path(directory)/'out')
            self.assertEqual(report['triage']['main_track_candidates'], 1)
            self.assertEqual(report['triage']['eligible_tooling_candidates'], 1)

    def test_replay_requires_matching_hash_and_never_fetches_missing_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'responses').mkdir()
            raw = b'[]'
            (root / 'responses/0000.json').write_bytes(raw)
            (root / 'receipts.json').write_text(json.dumps([{'route': '/test', 'file': '0000.json',
                'sha256': hashlib.sha256(raw).hexdigest()}]), encoding='utf-8')
            fetch = replay_fetch(root)
            self.assertEqual(fetch('/test'), [])
            with self.assertRaisesRegex(ValueError, 'uncached'):
                fetch('/missing')
            (root / 'responses/0000.json').write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                replay_fetch(root)

    def test_interrupted_collection_preserves_screened_candidates_and_failure_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run'
            def interrupted(repository, fetch, **kwargs):
                kwargs['on_candidate'](candidate())
                raise ValueError('GitHub connection failed')
            with patch('sys.argv', ['miner', '--repository', 'org/repo', '--output-dir', str(output)]), patch(
                    'examples.mine_upgradebench.collect', side_effect=interrupted), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(), 1)
            summary = json.loads((output / 'mining.json').read_text())
            self.assertEqual(summary['status'], 'partial')
            self.assertEqual(summary['counts']['input'], 1)
            self.assertEqual(summary['ready_tasks'], 0)
            report = json.loads((output / 'screening/candidates.json').read_text())
            self.assertFalse(report['provenance']['collection_complete'])
            self.assertEqual(len((output / 'collected.jsonl').read_text().splitlines()), 1)

    def test_http_errors_are_classified_without_exposing_credentials_or_body(self):
        cases = [
            (403, {'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '1800000000'}, 'rate limit', 'primary_rate_limit'),
            (403, {'retry-after': '60'}, 'secondary rate limit', 'secondary_rate_limit'),
            (401, {}, 'Bad credentials', 'authentication_failed'),
            (422, {}, 'Validation Failed', 'request_validation_failed'),
            (403, {}, 'Resource not accessible by personal access token', 'permission_denied'),
            (403, {'retry-after': 'untrusted-secret'}, 'proxy denied', 'http_access_error'),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, (status, headers, message, expected) in enumerate(cases):
                with self.subTest(category=expected):
                    api = GitHub(Path(directory) / str(index))
                    error = urllib.error.HTTPError('https://api.github.com', status, 'Forbidden', headers,
                        io.BytesIO(json.dumps({'message': message + ' credential-secret'}).encode()))
                    with patch.dict(os.environ, {'GITHUB_TOKEN': 'credential-secret'}), patch(
                            'urllib.request.urlopen', side_effect=error):
                        with self.assertRaises(ValueError) as caught:
                            api.get('/repos/org/repo/pulls')
                    self.assertEqual(api.last_error['category'], expected)
                    self.assertTrue(api.last_error['authenticated'])
                    self.assertNotIn('secret', str(caught.exception) + json.dumps(api.last_error))
                    self.assertEqual(list(api.output.iterdir()), [])

    def test_valid_candidate_is_not_a_ready_benchmark_task(self):
        result = screen(candidate())
        self.assertTrue(result['eligible_candidate'])
        self.assertFalse(result['benchmark_ready'])
        self.assertIn('base_fails_gold_passes_same_acceptance', result['pending_checks'])
        self.assertEqual(result['id'], 'org__repo-1')

    def test_test_only_dependency_only_and_unmerged_candidates_are_rejected(self):
        row = candidate()
        row.update(merged=False, files=['pyproject.toml', 'tests/test_app.py', 'docs/usage.py'], ci_paths=[])
        reasons = screen(row)['reasons']
        self.assertIn('not_merged', reasons)
        self.assertIn('no_non_test_source_change', reasons)
        self.assertIn('no_ci_configuration_evidence', reasons)
        row['files'] = ['src/app.py']
        reasons = screen(row)['reasons']
        self.assertIn('fewer_than_three_changed_files', reasons)
        self.assertIn('no_dependency_manifest_change', reasons)

    def test_unsafe_paths_and_unpinned_commits_fail_closed(self):
        for change in [{'files': ['../outside.py']}, {'base_commit': 'main'},
                       {'gold_commit': 'a' * 40}, {'number': True}]:
            with self.assertRaises(ValueError):
                screen({**candidate(), **change})

    def test_freeze_review_sample_is_seeded_order_independent_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [candidate(i) for i in range(1, 12)]
            first = freeze_candidates(rows, root / 'first')
            second = freeze_candidates(list(reversed(rows)), root / 'second')
            self.assertEqual(first['manual_review']['sample_ids'], second['manual_review']['sample_ids'])
            self.assertEqual(first['candidate_manifest_sha256'], second['candidate_manifest_sha256'])
            self.assertEqual(len(first['manual_review']['sample_ids']), 2)
            self.assertEqual(first['manual_review']['status'], 'pending')
            with self.assertRaises(FileExistsError):
                freeze_candidates(rows, root / 'first')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                freeze_candidates([candidate(), candidate()], root / 'duplicate')
            self.assertFalse((root / 'duplicate').exists())

    def test_collector_pins_merge_first_parent_and_checks_file_completeness(self):
        calls = []
        def fetch(route):
            calls.append(route)
            if '/pulls?' in route:
                return [{'merged_at': 'date', 'title': 'Upgrade library', 'number': 7}]
            if '/files?' in route:
                return [{'filename': name} for name in candidate()['files']]
            if '/pulls/' in route:
                return {'changed_files': 3, 'merge_commit_sha': 'b' * 40, 'title': 'Upgrade library',
                        'merged': True, 'base': {'sha': 'c' * 40}}
            if '/commits/' in route:
                return {'sha': 'b' * 40, 'parents': [{'sha': 'a' * 40}]}
            return {'truncated': False, 'tree': [{'type': 'blob', 'path': '.github/workflows/test.yml'}]}
        rows = collect('org/repo', fetch)
        self.assertEqual(rows[0]['base_commit'], 'a' * 40)
        self.assertEqual(rows[0]['gold_commit'], 'b' * 40)
        def search_fetch(route):
            if route == '/repos/org/repo':
                return {'full_name': 'org/repo'}
            if route.startswith('/search/issues?'):
                return {'incomplete_results': False, 'items': [{'number': 7}]}
            return fetch(route)
        self.assertEqual(collect('org/repo', search_fetch, discovery='search'), rows)
        def incomplete(route):
            value = fetch(route)
            return value[:1] if '/files?' in route else value
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            collect('org/repo', incomplete)
        def truncated(route):
            value = fetch(route)
            if '/git/trees/' in route:
                value['truncated'] = True
            return value
        with self.assertRaisesRegex(ValueError, 'Incomplete CI'):
            collect('org/repo', truncated)
