import unittest
from examples.review_independent_candidates import review_rows


class EligibleReviewTests(unittest.TestCase):
    def test_single_eligible_row_can_be_reviewed_without_replacing_shortlist(self):
        row = {'number': 1, 'eligible_metadata_only': True, 'reasons': []}
        report = {'collection_complete': True, 'status': 'insufficient_candidates',
                  'screened': [row, {'eligible_metadata_only': False, 'reasons': ['no_version']}], 'selected': []}
        self.assertEqual(review_rows(report, True), [row])
        self.assertEqual(report['selected'], [])
        with self.assertRaises(ValueError):
            review_rows(report)

    def test_incomplete_or_empty_candidate_sets_cannot_be_promoted(self):
        for complete, rows in ((False, [{'eligible_metadata_only': True, 'reasons': []}]), (True, [])):
            with self.assertRaises(ValueError):
                review_rows({'collection_complete': complete, 'status': 'insufficient_candidates', 'screened': rows}, True)
