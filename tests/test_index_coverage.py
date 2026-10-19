from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compass.coverage import index_coverage
from compass.index import build_index, RepositoryIndex
from compass.sweep import run_swe_sweep


class CoverageTests(unittest.TestCase):
    def test_explicit_scope_rechecks_invalid_bytes_without_changing_completeness(self):
        # Same general policy on two separate tasks, no repository/path allowlist.
        for filename in ['broken_fixture.py', 'another_module.py']:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root/'valid.py').write_text('def run():\n    pass\n')
                (root/filename).write_text('def bad(:\n')
                build_index(root, parser='python-ast')
                with RepositoryIndex(root) as index:
                    self.assertFalse(index_coverage(index)['eligible'])
                    coverage = index_coverage(index, 'valid-python')
                    self.assertTrue(coverage['eligible'])
                    self.assertEqual(coverage['excluded'][0]['path'], filename)
                    self.assertEqual(len(coverage['excluded'][0]['sha256']), 64)
                    self.assertFalse(index.metadata['complete'])
                    self.assertFalse(index.find_symbol('run')['complete'])
                    (root/filename).write_text('def fixed(): pass\n')
                    changed = index_coverage(index, 'valid-python')
                    self.assertFalse(changed['eligible'])
                    self.assertIn('changed', changed['blocked'][0]['reason'])

    def test_valid_python_parser_defect_and_file_limit_remain_blocked(self):
        for invalid in [False, True]:
            with self.subTest(file_limit=invalid), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root/'valid.py').write_text('#'+'x'*1_000_001 if invalid else 'def f(): pass\n')
                if invalid:
                    build_index(root, parser='python-ast')
                else:
                    with patch('compass.index.PythonParser.parse', side_effect=ValueError('extractor defect')):
                        build_index(root, parser='python-ast')
                with RepositoryIndex(root) as index:
                    result = index_coverage(index, 'valid-python')
                    self.assertFalse(result['eligible'])
                    self.assertEqual(result['excluded'], [])
                    self.assertTrue(result['blocked'])

    def test_sweep_does_not_admit_unindexed_reference_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'broken.py').write_text('def bad(:\n')
            build_index(root, parser='python-ast')
            response = {'complete': False, 'unindexed_gold_files': ['broken.py'],
                        'routing': {'mode_status': 'not_needed'}}
            instance = {'id': 'fixture', 'base_commit': 'a'*40, 'provenance': {}, 'query': 'query'}
            with RepositoryIndex(root) as index, patch('compass.sweep.evaluate_swe', return_value=response):
                result = run_swe_sweep(index, instance, root/'sweep', modes=['t0'], line_budgets=[1],
                                       repeats=1, coverage_policy='valid-python')
            self.assertFalse(result['all_passed'])
            self.assertEqual(result['summary'][0]['exclusions'], ['unindexed_reference_files'])
            self.assertFalse(result['index_metadata']['complete'])
