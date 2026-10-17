import unittest
from examples import reproduce_flask_login_813 as original
from examples import reproduce_flask_login_issue5279 as historical


class HistoricalRangeTests(unittest.TestCase):
    def comparison(self):
        return {'status': 'ahead', 'base_commit': {'sha': historical.BASE},
                'merge_base_commit': {'sha': historical.BASE}, 'total_commits': 5,
                'files': [{'filename': 'src/flask_login/utils.py', 'status': 'modified'}]}

    def test_acceptance_and_dependency_pins_are_not_weakened(self):
        self.assertEqual(historical.PROBE, original.PROBE)
        self.assertEqual(historical.CASES, original.CASES)
        self.assertEqual(historical.COMMON, original.COMMON)
        self.assertEqual(historical.TARGETS, original.TARGETS)
        self.assertIn('empty', historical.PROBE)

    def test_verified_bounded_ancestor_range(self):
        result = historical.verify_comparison(self.comparison())
        self.assertEqual(result['files'], ['src/flask_login/utils.py'])
        self.assertEqual(result['total_commits'], 5)

    def test_divergence_wrong_base_or_unbounded_range_is_rejected(self):
        for key, value in [('status', 'diverged'), ('merge_base_commit', {'sha': 'c'*40}),
                           ('base_commit', {'sha': 'c'*40}), ('total_commits', 21), ('files', [])]:
            comparison = self.comparison()
            comparison[key] = value
            with self.assertRaises(ValueError):
                historical.verify_comparison(comparison)
