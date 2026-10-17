from pathlib import Path
import subprocess
import tempfile
import unittest
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
            (root/'wrong.inc').write_bytes(b'latin-1: \xdf\xfc\n')
            git('add', 'wrong.inc')
            git('commit', '-qm', 'raw encoding fixture')
            (root/'.gitattributes').write_bytes(b'wrong.inc working-tree-encoding=latin-1\n')
            git('add', '.gitattributes')
            git('commit', '-qm', 'upstream encoding attribute')
            head = git('rev-parse', 'HEAD').stdout.decode().strip()
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
