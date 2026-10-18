import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compass.preparation import publish_snapshot


class PublicationTests(unittest.TestCase):
    def test_transient_lock_retries_then_checks_published_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            staging, destination = root/'repo.partial', root/'repo'
            staging.mkdir()
            original = Path.rename
            calls = []
            def rename(path, target):
                calls.append(path)
                if len(calls) == 1:
                    raise PermissionError('sharing violation')
                return original(path, target)
            with patch.object(Path, 'rename', rename), patch('compass.preparation.time.sleep'), \
                 patch('compass.preparation.check_snapshot') as check:
                publish_snapshot(staging, destination, 'a'*40)
            check.assert_called_once_with(destination, 'a'*40)
            self.assertTrue(destination.is_dir())
            events = json.loads((root/'repo.publication.json').read_text())['events']
            self.assertEqual([row['status'] for row in events], ['permission_error', 'published'])

    def test_persistent_lock_preserves_staging_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            staging = root/'repo.partial'
            staging.mkdir()
            with patch.object(Path, 'rename', side_effect=PermissionError('locked')) as rename, \
                 patch('compass.preparation.time.sleep'):
                with self.assertRaises(PermissionError):
                    publish_snapshot(staging, root/'repo', 'a'*40)
            self.assertEqual(rename.call_count, 4)
            self.assertTrue(staging.is_dir())

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'repo.partial').mkdir()
            (root/'repo').mkdir()
            with patch.object(Path, 'rename') as rename:
                with self.assertRaises(FileExistsError):
                    publish_snapshot(root/'repo.partial', root/'repo', 'a'*40)
            rename.assert_not_called()
