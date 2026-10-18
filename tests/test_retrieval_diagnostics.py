from pathlib import Path
import tempfile
import unittest

from examples.analyze_retrieval_candidates import diagnose


class RetrievalDiagnosticsTests(unittest.TestCase):
    def instance(self, root):
        (root/'a.py').write_text('x\n'*12)
        return dict(repo=str(root), core_regions=[dict(path='a.py', start=8, end=12)],
                    optional_regions=[], core_files=['a.py'])

    def test_late_candidates_can_be_found_but_not_emitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = self.instance(Path(temporary))
            rows = [dict(path='a.py', start_line=1, end_line=4),
                    dict(path='a.py', start_line=8, end_line=12)]
            result = diagnose(rows, instance, line_budget=3, cap=3)
            self.assertEqual(result['first_core_overlap_rank'], 2)
            self.assertEqual(result['full_candidate_core_lines'], 5)
            self.assertEqual(result['capped_candidate_core_lines'], 3)
            self.assertEqual(result['emitted_core_lines'], 0)
            self.assertEqual(result['optimistic_line_oracle']['gap_to_capped_line_oracle'], 3)

    def test_prefix_loss_distinct_from_rank_budget_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = self.instance(Path(temporary))
            result = diagnose([dict(path='a.py', start_line=5, end_line=12)], instance, cap=2)
            self.assertEqual(result['loss_decomposition'], dict(absent_from_saved_candidates=0,
                removed_by_per_chunk_prefix_cap=5, not_emitted_under_ranked_budget=0))

    def test_overlap_deduplicated_and_missing_core_counted(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = self.instance(Path(temporary))
            row = dict(path='a.py', start_line=8, end_line=9)
            result = diagnose([row, row], instance)
            self.assertEqual(result['full_candidate_core_lines'], 2)
            self.assertEqual(result['emitted_core_lines'], 2)
            self.assertEqual(sum(result['loss_decomposition'].values())+result['emitted_core_lines'], 5)


if __name__ == '__main__':
    unittest.main()
