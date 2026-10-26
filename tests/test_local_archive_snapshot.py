import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from compass.preparation import prepare_archive_snapshot,check_archive_snapshot


class LocalArchiveSnapshotTests(unittest.TestCase):
    commit='a'*40

    def exporter(self,members):
        def run(command,**kwargs):
            self.assertIn('archive',command);self.assertNotIn('fetch',command)
            self.assertEqual(command[-1],self.commit)
            self.assertTrue(kwargs['check']);self.assertGreater(kwargs['timeout'],0)
            with zipfile.ZipFile(command[command.index('--output')+1],'w') as out:
                out.comment=self.commit.encode()
                for name,value in members:
                    out.writestr(name,value)
        return run

    def source(self,root):
        source=root/'source';(source/'.git').mkdir(parents=True)
        (source/'code.py').write_text('dirty working tree must not be copied')
        return source

    def test_pinned_archive_bytes_empty_files_reuse_and_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.source(root);dest=root/'export'
            with patch('compass.preparation.subprocess.run',side_effect=self.exporter([('code.py','original\n'),('__init__.py','')])) as run:
                prepare_archive_snapshot('demo/demo',self.commit,dest,source=source)
                self.assertEqual((dest/'code.py').read_bytes(),b'original\n')
                self.assertEqual((dest/'__init__.py').read_bytes(),b'')
                prepare_archive_snapshot('demo/demo',self.commit,dest,source=source)
                self.assertEqual(run.call_count,1)
            self.assertFalse((dest/'.git').exists())
            self.assertEqual(check_archive_snapshot(dest,self.commit)['base_commit'],self.commit)
            (dest/'code.py').write_text('changed')
            with self.assertRaisesRegex(ValueError,'contents changed'):check_archive_snapshot(dest,self.commit)

    def test_unsafe_paths_links_collisions_and_metadata_never_publish(self):
        link=zipfile.ZipInfo('link.py');link.create_system=3;link.external_attr=(stat.S_IFLNK|0o777)<<16
        cases=[[('../outside.py','bad')],[('..\\outside.py','bad')],[('.git/config','bad')],
               [('A.py','one'),('a.py','two')],[(link,'target.py')]]
        for members in cases:
            with self.subTest(members=members),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);source=self.source(root);dest=root/'export'
                with patch('compass.preparation.subprocess.run',side_effect=self.exporter(members)):
                    with self.assertRaises(ValueError):prepare_archive_snapshot('demo/demo',self.commit,dest,source=source)
                self.assertFalse(dest.exists());self.assertFalse((root/'outside.py').exists())
                self.assertTrue((root/'export.partial').exists())

    def test_existing_partial_archive_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.source(root);archive=root/'export.archive.zip';archive.write_bytes(b'prior failure')
            with patch('compass.preparation.subprocess.run') as run:
                with self.assertRaises(FileExistsError):prepare_archive_snapshot('demo/demo',self.commit,root/'export',source=source)
            self.assertEqual(archive.read_bytes(),b'prior failure');run.assert_not_called()
