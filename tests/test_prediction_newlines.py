from pathlib import Path
import subprocess
import tempfile
import unittest

from keel.swebench import workspace_patch


class PredictionNewlineTests(unittest.TestCase):
    def test_export_roundtrip_preserves_content_attributes_and_workspace(self):
        for kind in ('lf', 'crlf_blob', 'explicit_raw', 'binary'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)

                def git(*args, **kwargs):
                    return subprocess.run(['git', '-c', 'safe.directory='+root.as_posix(),
                        '-c', 'core.autocrlf=false', '-c', 'user.name=Test',
                        '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false',
                        '-C', str(root), *args], capture_output=True, check=True, timeout=30, **kwargs)

                git('init', '-q')
                path = root/'data.txt'
                base = b'first\nvalue=1\nlast\n'
                if kind in ('crlf_blob', 'explicit_raw'):
                    base = base.replace(b'\n', b'\r\n')
                if kind == 'binary':
                    base = b'\x00'+base
                if kind == 'explicit_raw':
                    (root/'.gitattributes').write_bytes(b'data.txt -text\n')
                path.write_bytes(base)
                git('add', '.')
                git('commit', '-qm', 'fixture')
                task = {'base_commit': git('rev-parse', 'HEAD').stdout.decode().strip()}
                candidate = base.replace(b'value=1', b'value=2')
                if kind == 'lf':
                    candidate = candidate.replace(b'\n', b'\r\n')
                path.write_bytes(candidate)
                index_before = (root/'.git/index').read_bytes()
                patch = workspace_patch(root, task).encode('utf-8')
                self.assertEqual(path.read_bytes(), candidate)
                self.assertEqual((root/'.git/index').read_bytes(), index_before)
                if kind == 'lf':
                    self.assertNotIn(b'\r', patch)
                    self.assertIn(b'-value=1\n+value=2\n', patch)
                    self.assertNotIn(b'-first', patch)
                git('checkout', '--', 'data.txt')
                git('apply', '--binary', '-', input=patch)
                expected = candidate.replace(b'\r\n', b'\n') if kind == 'lf' else candidate
                self.assertEqual(path.read_bytes(), expected)

    def test_newline_only_change_does_not_export_a_text_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.run(['git', '-c', 'safe.directory='+root.as_posix(),
                    '-c', 'core.autocrlf=false', '-c', 'user.name=Test',
                    '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false',
                    '-C', str(root), *args], capture_output=True, check=True, timeout=30)
            git('init', '-q')
            (root/'a.py').write_bytes(b'VALUE = 1\n')
            git('add', '.')
            git('commit', '-qm', 'fixture')
            task = {'base_commit': git('rev-parse', 'HEAD').stdout.decode().strip()}
            (root/'a.py').write_bytes(b'VALUE = 1\r\n')
            self.assertEqual(workspace_patch(root, task), '')
