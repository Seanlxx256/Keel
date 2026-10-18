import json
from importlib import metadata
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from examples.cocoindex_retrieval_worker import copy_snapshot, parse_search, retrieve


class CocoIndexRetrievalTests(unittest.TestCase):
    def test_parse_preserves_native_order_and_one_based_ranges(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'a.py').write_text('one\ntwo\nthree\n')
            result = parse_search({'success': True, 'results': [
                dict(file_path='a.py', start_line=2, end_line=3),
                dict(file_path='a.py', start_line=1, end_line=1)]}, root)
            self.assertEqual([r['start_line'] for r in result], [2, 1])

    def test_failed_response_is_not_an_empty_success(self):
        with self.assertRaises(ValueError):
            parse_search({'success': False, 'results': []}, Path.cwd())
        with self.assertRaises(ValueError):
            parse_search({'success': True}, Path.cwd())

    def test_rejects_outside_and_out_of_range_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root/'repo'
            repo.mkdir()
            (root/'outside.py').write_text('x\n')
            (repo/'a.py').write_text('x\n')
            for path, start, end in [('../outside.py', 1, 1), ('a.py', 0, 1),
                                      ('a.py', 1, 2), ('a.py', True, 1)]:
                with self.subTest(path=path, start=start, end=end), self.assertRaises(ValueError):
                    parse_search({'success': True, 'results': [dict(file_path=path,
                        start_line=start, end_line=end)]}, repo)

    def test_missing_package_persists_unavailable_without_copying(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'result.json'
            with patch('examples.cocoindex_retrieval_worker.metadata.version',
                       side_effect=metadata.PackageNotFoundError('cocoindex-code')):
                result = retrieve({'model_cache': str(Path(temporary)/'models')}, output)
            self.assertEqual(result['status'], 'unavailable')
            self.assertNotIn('candidates', result)
            self.assertFalse((Path(temporary)/'snapshot').exists())
            self.assertEqual(json.loads(output.read_text())['stage'], 'package_probe')

    def test_copy_uses_tracked_files_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root/'repo'
            repo.mkdir()
            subprocess.run(['git', 'init', str(repo)], capture_output=True, check=True)
            (repo/'a.py').write_bytes(b'x = 1\r\n')
            subprocess.run(['git', '-c', 'safe.directory='+str(repo), 'add', 'a.py'], cwd=repo,
                           capture_output=True, check=True)
            (repo/'untracked.json').write_text('not part of corpus')
            manifest = copy_snapshot(repo, root/'copy')
            self.assertEqual(list(manifest), ['a.py'])
            self.assertEqual((root/'copy/a.py').read_bytes(), b'x = 1\r\n')
            self.assertFalse((root/'copy/.git').exists())
            self.assertFalse((root/'copy/untracked.json').exists())


if __name__ == '__main__':
    unittest.main()
