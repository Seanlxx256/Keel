import unittest
from examples.prepare_issue_candidate import collect_pair


class IssueCandidateTests(unittest.TestCase):
    def fetch(self, route):
        if route == '/repos/org/old':
            return {'full_name': 'org/new'}
        if route.endswith('/pulls/3'):
            return {'number': 3, 'merged': True, 'merge_commit_sha': 'b'*40, 'changed_files': 1}
        if route.endswith('/issues/4'):
            return {'number': 4, 'body': 'ImportError: removed API'}
        if '/commits/' in route:
            return {'sha': 'b'*40, 'parents': [{'sha': 'a'*40}]}
        return [{'filename': 'source.py', 'status': 'modified'}]

    def test_fixed_issue_pair_uses_verified_parent_and_transfer(self):
        report = collect_pair(self.fetch, 'org/old', 3, 'other/report', 4)
        self.assertEqual(report['repository'], 'org/new')
        self.assertEqual(report['base_commit'], 'a'*40)
        self.assertFalse(report['benchmark_ready'])
        self.assertEqual(report['reported_issue']['body'], 'ImportError: removed API')

    def test_wrong_commit_and_incomplete_file_page_fail(self):
        for mode in ('parent', 'files', 'unmerged'):
            def fetch(route):
                value = self.fetch(route)
                if mode == 'parent' and '/commits/' in route:
                    value['sha'] = 'c'*40
                if mode == 'files' and '/files?' in route:
                    return []
                if mode == 'unmerged' and route.endswith('/pulls/3'):
                    value['merged'] = False
                return value
            with self.assertRaises(ValueError):
                collect_pair(fetch, 'org/old', 3, 'other/report', 4)
