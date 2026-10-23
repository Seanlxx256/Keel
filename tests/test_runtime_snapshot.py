import tempfile
import unittest
from pathlib import Path

from keel.runtime_snapshot import create_snapshot,verify_snapshot


class SnapshotTests(unittest.TestCase):
    def fixture(self,root):
        (root/'keel').mkdir();(root/'keel/a.py').write_bytes(b'VALUE = 1\r\n')
        (root/'pyproject.toml').write_text('[project]\nname="fixture"\n')

    def test_snapshot_preserves_bytes_and_survives_live_workspace_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root);frozen=root/'archive'
            create_snapshot(root,frozen)
            (root/'keel/a.py').write_text('VALUE = 2\n')
            verify_snapshot(frozen)
            self.assertEqual((frozen/'runtime/keel/a.py').read_bytes(),b'VALUE = 1\r\n')
            with self.assertRaises(FileExistsError):create_snapshot(root,frozen)

    def test_changed_and_added_snapshot_source_rejected(self):
        for kind in ('changed','added'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);self.fixture(root);frozen=root/'archive';create_snapshot(root,frozen)
                target=frozen/'runtime/keel'/('a.py' if kind=='changed' else 'b.py')
                target.write_text('VALUE = 3\n')
                with self.assertRaises(ValueError):verify_snapshot(frozen)
