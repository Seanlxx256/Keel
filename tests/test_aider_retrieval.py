from collections import namedtuple
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.aider_retrieval_worker import source_regions, tag_candidates
from examples.setup_aider_retrieval import setup


class AiderRetrievalTests(unittest.TestCase):
    def test_native_tag_order_zero_based_lines_and_ast_extent(self):
        tag = namedtuple('Tag', 'rel_fname name line')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root/'a.py').write_text('@decorator\ndef first():\n    pass\n\ndef second():\n    return 1\n')
            rows, skipped = tag_candidates([tag('a.py', 'second', 4),
                tag('a.py', 'first', 1), tag('a.py', 'first', 1), ('a.py',)], root)
            self.assertEqual([(r['start_line'],r['end_line']) for r in rows], [(5,6),(1,3)])
            self.assertEqual(skipped, 1)

    def test_invalid_python_and_escaping_tags_not_fabricated(self):
        tag = namedtuple('Tag', 'rel_fname name line')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo = root/'repo'
            repo.mkdir()
            (repo/'bad.py').write_text('def broken(:')
            self.assertEqual(source_regions(repo/'bad.py'), {})
            (root/'outside.py').write_text('def outside(): pass')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                tag_candidates([tag('../outside.py','outside',0)],repo)

    def test_missing_environment_is_explicit_and_no_installs_when_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = setup(root/'output', root/'absent', None, skip_install=True, timeout=10)
            self.assertEqual(result['commands'], [])
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['error_type'], 'FileNotFoundError')


if __name__ == '__main__':
    unittest.main()
