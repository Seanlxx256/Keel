from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from examples.mine_upgradebench import collect
from examples.run_autonomous_campaign import campaign
from keel.task_factory import has_upstream_test_change, automatic_acceptance_supported


class IntakeTests(unittest.TestCase):
    def test_testless_pr_is_excluded_before_commit_fetch_and_does_not_fill_quota(self):
        routes, skips = [], []
        def fetch(route):
            routes.append(route)
            if route == '/repos/org/library':
                return {'full_name': 'org/library'}
            if route.startswith('/search/issues?'):
                return {'incomplete_results': False, 'items': [{'number': 1}, {'number': 2}]}
            if route.endswith('/pulls/1') or route.endswith('/pulls/2'):
                return {'merged': True, 'changed_files': 2, 'title': 'Dependency compatibility', 'merge_commit_sha': 'b'*40}
            if '/pulls/1/files?' in route:
                return [{'filename': 'src/library.py'}, {'filename': 'README.md'}]
            if '/pulls/2/files?' in route:
                return [{'filename': 'src/library.py'}, {'filename': 'tests/test_library.py', 'status': 'modified'}]
            if '/commits/' in route:
                return {'sha': 'b'*40, 'parents': [{'sha': 'a'*40}]}
            if '/git/trees/' in route:
                return {'truncated': False, 'tree': []}
            raise AssertionError(route)
        rows = collect('org/library', fetch, limit=1, discovery='search', query='compatibility',
                       file_predicate=has_upstream_test_change, on_skip=skips.append)
        self.assertEqual([row['number'] for row in rows], [2])
        self.assertEqual(skips[0]['number'], 1)
        self.assertEqual(sum('/commits/' in route for route in routes), 1)

    def test_removed_or_unsupported_test_layout_is_not_enough(self):
        for entries in ([{'filename': 'tests/test_lib.py', 'status': 'removed'}],
                        [{'filename': 'source/tests/test_lib.py'}], [{'filename': 'tests/conftest.py'}]):
            self.assertFalse(has_upstream_test_change(entries))
        self.assertTrue(has_upstream_test_change([{'filename': 'tests/test_lib.py', 'status': 'added'}]))

    def test_removed_test_module_rejects_candidate_even_with_other_modified_tests(self):
        entries = [{'filename': 'src/lib.py', 'status': 'modified'},
                   {'filename': 'tests/new_test.py', 'status': 'modified'},
                   {'filename': 'tests/old_test.py', 'status': 'removed'}]
        self.assertFalse(automatic_acceptance_supported(entries))
        self.assertTrue(automatic_acceptance_supported(entries[:2]))

    def test_queries_share_seen_numbers_before_fetching_pr_metadata(self):
        seen, calls = set(), []
        def fetch(route):
            calls.append(route)
            if route == '/repos/org/lib':
                return {'full_name': 'org/lib'}
            if route.startswith('/search/issues?'):
                return {'incomplete_results': False, 'items': [{'number': 1}]}
            if route.endswith('/pulls/1'):
                return {'merged': True, 'changed_files': 1, 'title': 'Compatibility'}
            if '/pulls/1/files?' in route:
                return [{'filename': 'src/lib.py'}]
            raise AssertionError(route)
        for query in ('compatibility', 'migration', 'upgrade'):
            collect('org/lib', fetch, discovery='search', query=query,
                    file_predicate=automatic_acceptance_supported, seen_numbers=seen)
        self.assertEqual(sum(route.endswith('/pulls/1') for route in calls), 1)

    def test_environment_unresolved_repository_does_not_fill_runnable_pool(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api = Mock()
            api.receipts = []
            def rows(repository, fetch, **kwargs):
                kwargs['on_candidate']({'repository': repository, 'number': 1, 'title': 'Compatibility',
                                        'base_commit': 'a'*40, 'gold_commit': 'b'*40})
            with patch('examples.run_autonomous_campaign.GitHub', return_value=api), \
                 patch('examples.run_autonomous_campaign.from_config'), \
                 patch('examples.run_autonomous_campaign.implementation_hashes', return_value={}), \
                 patch('keel.evaluation_protocol.registry', return_value={'tasks': []}), \
                 patch('examples.run_autonomous_campaign.discover', return_value=['org/first', 'org/second']), \
                 patch('examples.run_autonomous_campaign.collect', side_effect=rows), \
                 patch('examples.run_autonomous_campaign.prepare_snapshot', return_value=root), \
                 patch('examples.run_autonomous_campaign.construct', return_value=({'status': 'environment_unresolved'}, {})):
                report = campaign(root, root/'campaign', {}, repository_limit=1, candidates_per_repo=1)
            self.assertEqual(report['repositories'], ['org/first', 'org/second'])
            self.assertEqual(report['runnable_repositories'], [])
            self.assertEqual(report['eligible_repositories'], 2)

    def test_automatic_pool_continues_past_repository_without_eligible_prs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api = Mock()
            api.receipts = []
            def collect_rows(repository, fetch, **kwargs):
                if repository == 'org/no-tests':
                    kwargs['on_skip']({'number': 1, 'reason': 'automatic_acceptance_prerequisite_missing'})
                    return []
                kwargs['on_candidate']({'repository': repository, 'number': 2,
                    'title': 'Compatibility', 'base_commit': 'a'*40, 'gold_commit': 'b'*40})
            with patch('examples.run_autonomous_campaign.GitHub', return_value=api), \
                 patch('examples.run_autonomous_campaign.from_config', return_value=Mock()), \
                 patch('examples.run_autonomous_campaign.implementation_hashes', return_value={}), \
                 patch('keel.evaluation_protocol.registry', return_value={'tasks': []}), \
                 patch('examples.run_autonomous_campaign.discover', return_value=['org/no-tests', 'org/with-tests']), \
                 patch('examples.run_autonomous_campaign.collect', side_effect=collect_rows), \
                 patch('examples.run_autonomous_campaign.prepare_snapshot', return_value=root), \
                 patch('examples.run_autonomous_campaign.construct', return_value=({'status': 'environment_unresolved'}, {})):
                report = campaign(root, root/'campaign', {}, repository_limit=1)
            self.assertEqual(report['repositories'], ['org/no-tests', 'org/with-tests'])
            self.assertEqual(report['eligible_repositories'], 1)
            self.assertEqual(report['status'], 'no_runnable_tasks')
            self.assertEqual(report['repository_results'][0]['status'], 'no_eligible_candidates')
            self.assertEqual(report['repository_results'][0]['excluded_prerequisites'], 1)

    def test_local_search_limit_continues_to_next_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api = Mock()
            api.receipts = []
            def collect_rows(repository, fetch, **kwargs):
                if repository == 'org/expensive':
                    for _ in range(17):
                        fetch('/bounded-route')
            with patch('examples.run_autonomous_campaign.GitHub', return_value=api), \
                 patch('examples.run_autonomous_campaign.from_config', return_value=Mock()), \
                 patch('examples.run_autonomous_campaign.implementation_hashes', return_value={}), \
                 patch('examples.run_autonomous_campaign.collect', side_effect=collect_rows):
                report = campaign(root, root/'campaign', {}, repositories=['org/expensive', 'org/next'])
            self.assertEqual([row['status'] for row in report['repository_results']], ['search_limit', 'no_eligible_candidates'])
            self.assertEqual(api.get.call_count, 16)
            self.assertEqual(report['budget']['tool_calls'], 16)
            self.assertEqual(report['status'], 'no_runnable_tasks')
