import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from keel.checkpoint_archive import archive_checkpoints,restore_checkpoint,digest,safe_path


class CheckpointArchiveTests(unittest.TestCase):
    def test_invalid_deadlines_are_rejected_before_io(self):
        for value in (0,-1,True,float('inf'),float('nan')):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'deadline'):
                archive_checkpoints('missing','missing','missing','missing',seconds=value)
            with self.assertRaisesRegex(ValueError,'deadline'):restore_checkpoint('missing','missing',seconds=value)
    def fixture(self,tmp):
        base=Path(tmp);root=base/'workspace';root.mkdir();groups=[]
        for cell in ('numbered_end','id_free_end'):
            relative='scout-representation-comparison-v1/results/'+cell+'/training-run/training'
            training=root/'.keel/finetuning'/relative;training.mkdir(parents=True)
            steps=[]
            for i in range(1,169):
                folder=training/f'step-{i}';folder.mkdir()
                (folder/'adapter').write_bytes(('parameters'+str(i)).encode())
                step={'checkpoint_files':{'adapter':digest(folder/'adapter')}}
                (folder/'step.json').write_text(json.dumps(step));steps.append(step)
            (training/'training.json').write_text(json.dumps({'status':'passed','steps':steps}))
            (training.parent/'report.json').write_text(json.dumps({'status':'passed','training_sha256':digest(training/'training.json')}))
            groups.append({'training':relative,'final_step':168})
        proposal=root/'proposal.json';proposal.write_text(json.dumps({'groups':groups}))
        return root,proposal,base/'external/checkpoints.zip',root/'archive-record',groups

    def test_archive_restore_and_cleanup_recovery_keep_final_and_receipts(self):
        with tempfile.TemporaryDirectory() as tmp,patch('builtins.print'):
            root,proposal,archive,record,groups=self.fixture(tmp)
            final=root/'.keel/finetuning'/groups[0]['training']/'step-168/adapter';h=digest(final)
            r=archive_checkpoints(root,proposal,archive,record)
            self.assertEqual(r['status'],'completed');self.assertEqual(r['deleted_directories'],334)
            self.assertEqual(digest(final),h)
            relative='.keel/finetuning/'+groups[0]['training']+'/step-3'
            self.assertFalse((root/relative).exists())
            restore_checkpoint(record,relative)
            self.assertEqual((root/relative/'adapter').read_bytes(),b'parameters3')
            self.assertEqual(archive_checkpoints(root,proposal,archive,record)['status'],'completed')

    def test_corrupt_source_is_not_archived_or_deleted(self):
        with tempfile.TemporaryDirectory() as tmp,patch('builtins.print'):
            root,proposal,archive,record,groups=self.fixture(tmp)
            path=root/'.keel/finetuning'/groups[0]['training']/'step-1/adapter'
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'hash drift'):archive_checkpoints(root,proposal,archive,record)
            self.assertTrue(path.exists());self.assertFalse(archive.exists())

    def test_interrupted_deletion_reuses_verified_archive(self):
        with tempfile.TemporaryDirectory() as tmp,patch('builtins.print'):
            root,proposal,archive,record,groups=self.fixture(tmp)
            original=Path.unlink;calls=[0]
            def interrupted(path,*args,**kwargs):
                if path.name=='adapter':
                    calls[0]+=1
                    if calls[0]==2:raise OSError('simulated interruption')
                return original(path,*args,**kwargs)
            with patch.object(Path,'unlink',interrupted):
                with self.assertRaisesRegex(OSError,'simulated'):archive_checkpoints(root,proposal,archive,record)
            self.assertTrue(archive.exists());h=digest(archive)
            self.assertEqual(archive_checkpoints(root,proposal,archive,record)['status'],'completed')
            self.assertEqual(h,digest(archive))

    def test_failed_archive_verification_never_removes_source(self):
        with tempfile.TemporaryDirectory() as tmp,patch('builtins.print'):
            root,proposal,archive,record,groups=self.fixture(tmp)
            with patch('keel.checkpoint_archive.verify_zip',side_effect=ValueError('bad archive')):
                with self.assertRaisesRegex(ValueError,'bad archive'):archive_checkpoints(root,proposal,archive,record)
            self.assertTrue((root/'.keel/finetuning'/groups[0]['training']/'step-1/adapter').exists())

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in ('../outside','D:/outside','safe/../../outside'):
                with self.assertRaises(ValueError):safe_path(Path(tmp),value)
