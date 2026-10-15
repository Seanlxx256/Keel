from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from keel.candidate_review import compare_python, review_sources


class CandidateReviewTests(unittest.TestCase):
    def test_comments_are_equivalent_but_docstrings_and_code_remain_changes(self):
        self.assertFalse(compare_python(b'x = 1 # old comment\n', b'x = 1 # corrected comment\n')['ast_changed'])
        self.assertTrue(compare_python(b'"old doc"\nx = 1\n', b'"new doc"\nx = 1\n')['ast_changed'])
        self.assertTrue(compare_python(b'x = 1\n', b'x = 2\n')['ast_changed'])
        self.assertTrue(compare_python(None, b'x = 1\n')['ast_changed'])

    def test_unsupported_syntax_is_not_silently_treated_as_a_valid_task(self):
        result = compare_python(b'print "python2"\n', b'print("python3")\n')
        self.assertIsNone(result['ast_changed'])
        self.assertEqual(result['status'], 'unsupported_python_syntax')

    def test_comment_only_source_is_excluded_and_behavior_change_still_needs_reproduction(self):
        with tempfile.TemporaryDirectory() as directory:
            base, gold = Path(directory)/'base', Path(directory)/'gold'
            for path in (base, gold):
                path.mkdir()
                (path/'app.py').write_text('x = 1 # old\n')
            (gold/'app.py').write_text('x = 1 # fixed\n')
            row = {'base_commit': 'a'*40, 'gold_commit': 'b'*40, 'source_files_curator_only': ['app.py']}
            raw = SimpleNamespace(stdout='parent '+'a'*40+'\n\nmessage')
            with patch('keel.candidate_review.check_snapshot'), patch('keel.candidate_review.subprocess.run', return_value=raw):
                result = review_sources(row, base, gold)
                self.assertEqual(result['status'], 'excluded_no_python_ast_change')
                (gold/'app.py').write_text('x = 2\n')
                result = review_sources(row, base, gold)
                self.assertEqual(result['status'], 'needs_environment_reproduction')
                self.assertFalse(result['benchmark_ready'])
                (gold/'extra.py').write_text('unexpected = 1\n')
                with self.assertRaisesRegex(ValueError, 'source diff'):
                    review_sources(row, base, gold)
                raw.stdout = 'parent '+'c'*40+'\n\nmessage'
                with self.assertRaisesRegex(ValueError, 'parent'):
                    review_sources(row, base, gold)
