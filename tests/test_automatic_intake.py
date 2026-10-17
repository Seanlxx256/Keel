from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from examples.mine_upgradebench import collect
from examples.run_autonomous_campaign import campaign
from keel.task_factory import has_upstream_test_change


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
