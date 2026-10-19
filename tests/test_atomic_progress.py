import ctypes
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from compass.progress import atomic_json


class AtomicProgressTests(unittest.TestCase):
    def test_transient_permission_errors_retry_and_preserve_complete_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'progress.json'
            atomic_json(path, {'previous': True})
            original = Path.replace
            calls = []
            def replace(source, target):
                calls.append(str(source))
                if len(calls) < 3:
                    self.assertEqual(json.loads(path.read_text()), {'previous': True})
                    raise PermissionError('sharing violation')
                return original(source, target)
            with patch.object(Path, 'replace', new=replace):
                atomic_json(path, {'finished': True}, delay=0)
            self.assertEqual(len(calls), 3)
            self.assertEqual(json.loads(path.read_text()), {'finished': True})
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_persistent_error_is_bounded_and_old_state_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'progress.json'
            atomic_json(path, {'previous': True})
            with patch.object(Path, 'replace', side_effect=PermissionError('denied')) as replace:
                with self.assertRaises(PermissionError):
                    atomic_json(path, {'new': True}, attempts=3, delay=0)
            self.assertEqual(replace.call_count, 3)
            self.assertEqual(json.loads(path.read_text()), {'previous': True})

    @unittest.skipUnless(os.name == 'nt', 'Real Windows sharing semantics')
    def test_real_reader_without_delete_sharing_releases_during_retry(self):
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'progress.json'
            atomic_json(path, {'old': True})
            handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 128, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            release = threading.Timer(.1, lambda: kernel.CloseHandle(handle))
            release.start()
            try:
                atomic_json(path, {'new': True})
            finally:
                release.join()
            self.assertEqual(json.loads(path.read_text()), {'new': True})
