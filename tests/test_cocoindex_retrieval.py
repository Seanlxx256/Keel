import json
from importlib import metadata
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from examples.cocoindex_retrieval_worker import (copy_snapshot, parse_search, retrieve,
    restore_checkpoint, native_index_command)
import hashlib


class CocoIndexRetrievalTests(unittest.TestCase):
    def test_native_index_uses_canonical_project_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'child').mkdir()
            command = native_index_command(root/'child/..')
            self.assertEqual(command[-1], str(root.resolve()))
            self.assertIn('client.index(sys.argv[1]', command[3])
            self.assertNotIn('client.index("."', command[3])

    def test_checkpoint_clone_preserves_old_run_and_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            old = base/'old'
            native = old/'snapshot/.cocoindex_code'
            native.mkdir(parents=True)
            data = b'x = 1\n'
            (old/'snapshot/a.py').write_bytes(data)
            manifest = {'a.py': hashlib.sha256(data).hexdigest()}
            embedding = {'provider': 'sentence-transformers', 'model': 'same-model'}
            (old/'source-manifest.json').write_text(json.dumps(manifest))
            (old/'result.json').write_text(json.dumps(dict(daemon_cleanup_returncode=0,
                version='v1', embedding_settings=embedding)))
            (native/'settings.yml').write_text(json.dumps({'include_patterns': ['**/*.py']}))
            (native/'checkpoint').write_bytes(b'native-state')
            root = base/'new'
            root.mkdir()
            result = restore_checkpoint(old, root, manifest, 'v1', embedding)
            self.assertEqual(result['status'], 'cloned')
            (root/'.cocoindex_code/checkpoint').write_bytes(b'new-state')
            self.assertEqual((native/'checkpoint').read_bytes(), b'native-state')
            (old/'snapshot/a.py').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'source bytes differ'):
                restore_checkpoint(old, base/'other', manifest, 'v1', embedding)

    def test_blocked_transport_stops_before_snapshot_or_model_load(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'result.json'
            with patch('examples.cocoindex_retrieval_worker.metadata.version', return_value='test'), \
                    patch('examples.cocoindex_retrieval_worker.probe_named_pipe', return_value={
                        'status': 'unavailable', 'permission_boundary': True}) as probe, \
                    patch('examples.cocoindex_retrieval_worker.copy_snapshot') as copy:
                result = retrieve({'model_cache': str(Path(directory)/'models')}, output)
            copy.assert_not_called()
            probe.assert_called_once()
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['stage'], 'ipc_preflight')
            self.assertTrue(result['ipc_preflight']['permission_boundary'])
            self.assertFalse((Path(directory)/'snapshot').exists())
    def test_uninitialized_gitlink_recorded_but_initialized_submodule_not_silently_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root/'repo'
            repo.mkdir()
            subprocess.run(['git', 'init', str(repo)], capture_output=True, check=True)
            subprocess.run(['git', '-c', 'safe.directory='+str(repo), 'update-index', '--add',
                '--cacheinfo', '160000,'+'a'*40+',helpers'], cwd=repo, capture_output=True, check=True)
            (repo/'helpers').mkdir()
            omissions = []
            self.assertEqual(copy_snapshot(repo, root/'copy', omissions), {})
            self.assertEqual(omissions, [dict(path='helpers', commit='a'*40, reason='uninitialized_git_submodule')])
            (repo/'helpers/initialized.py').write_text('x = 1')
            with self.assertRaisesRegex(ValueError, 'Initialized submodule'):
                copy_snapshot(repo, root/'copy2')

    def test_declared_symlink_is_not_followed_or_copied_as_placeholder_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root/'repo'
            repo.mkdir()
            subprocess.run(['git', 'init', str(repo)], capture_output=True, check=True)
            subprocess.run(['git', '-c', 'safe.directory='+str(repo), 'update-index', '--add',
                '--cacheinfo', '120000,'+'b'*40+',link.py'], cwd=repo, capture_output=True, check=True)
            (repo/'link.py').write_text('../../outside.py')
            omissions = []
            self.assertEqual(copy_snapshot(repo, root/'copy', omissions), {})
            self.assertEqual(omissions[0]['reason'], 'git_symlink_not_indexed')
            self.assertFalse((root/'copy/link.py').exists())

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
