from pathlib import Path
import subprocess
import tempfile
import unittest
import os
from compass.benchmarks import check_snapshot


class SnapshotEncodingTests(unittest.TestCase):
    def test_raw_blob_identical_encoding_fixture_passes_but_real_edit_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args, **kwargs):
                return subprocess.run(['git', '-c', 'safe.directory='+root.as_posix(), '-C', str(root),
                    '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                    '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True, **kwargs)
            git('init', '-q')
            git('config', 'core.autocrlf', 'false')
            git('config', 'core.safecrlf', 'false')
            (root/'wrong.inc').write_bytes(b'latin-1: \xdf\xfc\n')
            git('add', 'wrong.inc')
            git('commit', '-qm', 'raw encoding fixture')
            (root/'.gitattributes').write_bytes(b'wrong.inc working-tree-encoding=latin-1\n')
            git('add', '.gitattributes')
            git('commit', '-qm', 'upstream encoding attribute')
            head = git('rev-parse', 'HEAD').stdout.decode().strip()
            # Adding attributes does not change the file's stat tuple. Some Git
            # builds trust the cached tuple and do not re-run encoding filters.
            # Invalidate it explicitly, without sleeping or changing raw bytes.
            path = root/'wrong.inc'
            before = path.stat()
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns+2_000_000_000))
            self.assertEqual(path.read_bytes(), git('show', head+':wrong.inc').stdout)
            self.assertNotEqual(git('diff', '--name-only').stdout, b'')
            check_snapshot(root, head)
            (root/'wrong.inc').write_bytes(b'changed: \xdf\xfc\n')
            with self.assertRaisesRegex(ValueError, 'tracked changes'):
                check_snapshot(root, head)

    def test_deleted_file_is_not_accepted_as_encoding_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.run(['git', '-c', 'safe.directory='+root.as_posix(), '-C', str(root),
                    '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                    '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True)
            git('init', '-q')
            (root/'a.py').write_bytes(b'VALUE = 1\n')
            git('add', '.')
            git('commit', '-qm', 'fixture')
            head = git('rev-parse', 'HEAD').stdout.decode().strip()
            (root/'a.py').unlink()
            with self.assertRaises(ValueError):
                check_snapshot(root, head)
