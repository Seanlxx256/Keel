import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

from keel.diagnostic_evidence import load_diagnostic_evidence
from keel.saved_repair import restore_seed_bytes


class SeedRestorationTests(unittest.TestCase):
    def git(self,repo,*args,input=None):
        result=subprocess.run(['git','-c','safe.directory='+repo.as_posix(),'-C',str(repo),*args],
                              input=input,capture_output=True,timeout=20)
        if result.returncode:raise AssertionError(result.stderr.decode(errors='replace'))
        return result.stdout

    def test_real_checkout_apply_and_strict_diagnostic_check_with_autocrlf_true(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            self.git(source,'init','-q');self.git(source,'config','user.email','fixture@example.invalid')
            self.git(source,'config','user.name','Fixture')
            (source/'sample.py').write_bytes(b'value=1\n')
            self.git(source,'-c','core.autocrlf=false','add','sample.py')
            self.git(source,'-c','core.autocrlf=false','commit','-qm','base')
            commit=self.git(source,'rev-parse','HEAD').decode().strip()
            (source/'sample.py').write_bytes(b'value=2\n')
            patch=self.git(source,'-c','core.autocrlf=false','diff','--binary')
            repo=root/'prepared'
            # Copy only this test's object database; no transport or external shell.
            shutil.copytree(source/'.git',repo/'.git')
            self.git(repo,'-c','core.autocrlf=false','checkout','--force','--detach',commit)
            self.git(repo,'config','core.autocrlf','true')
            self.git(repo,'apply','--binary','-',input=patch)
            self.assertEqual((repo/'sample.py').read_bytes(),b'value=2\r\n')
            sha=hashlib.sha256(b'value=2\n').hexdigest()
            observation={'kind':'execution','outcome':'completed','evidence_id':'E1','code':'print(2)',
                'execution':{'returncode':0,'timeout':False},
                'candidate_manifest':{'sample':{'path':'sample.py','sha256':sha}},
                'probe':{'returncode':0,'timeout':False,'stdout':'2','stderr':'__KEEL_CANDIDATE_IMPORTS__'+json.dumps([
                    {'module':'sample','status':'executed','sha256':sha}])}}
            report={'status':'completed_needs_review','workspace_unchanged':True,'acceptance':'not_executed',
                    'image_id':'fixture','diagnosis':{'observations':[observation]}}
            path=root/'report.json';path.write_text(json.dumps(report))
            path.with_name('receipt.json').write_text(json.dumps({'report_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'plan_sha256':'fixture'}))
            with self.assertRaisesRegex(ValueError,'source mismatch'):load_diagnostic_evidence(path,repo)
            repaired=restore_seed_bytes(repo,source,{'sample.py':sha})
            self.assertEqual(repaired['restored_files'],1)
            self.assertEqual(load_diagnostic_evidence(path,repo)['observations'][0]['probe']['stdout'],'2')
            self.assertEqual(restore_seed_bytes(repo,source,{'sample.py':sha})['restored_files'],0)
            self.git(repo,'-c','core.autocrlf=false','checkout','HEAD','--','sample.py')
            self.git(repo,'-c','core.autocrlf=false','apply','--binary','-',input=patch)
            self.assertEqual((repo/'sample.py').read_bytes(),b'value=2\n')

    def test_real_content_difference_rejects_entire_batch_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);repo=root/'repo';source=root/'source';repo.mkdir();source.mkdir()
            bindings={}
            for name in ('a.py','b.py'):
                (source/name).write_bytes(b'value=1\n');bindings[name]=hashlib.sha256(b'value=1\n').hexdigest()
            (repo/'a.py').write_bytes(b'value=1\r\n');(repo/'b.py').write_bytes(b'value=2\r\n')
            with self.assertRaisesRegex(ValueError,'real content'):restore_seed_bytes(repo,source,bindings)
            self.assertEqual((repo/'a.py').read_bytes(),b'value=1\r\n')
            with self.assertRaisesRegex(ValueError,'Invalid seed'):restore_seed_bytes(repo,source,{'../escape.py':'x'})

    def test_changed_original_seed_is_never_used_as_recovery_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);repo=root/'repo';source=root/'source';repo.mkdir();source.mkdir()
            (source/'a.py').write_bytes(b'value=2\n');(repo/'a.py').write_bytes(b'value=2\r\n')
            with self.assertRaisesRegex(ValueError,'source changed'):
                restore_seed_bytes(repo,source,{'a.py':hashlib.sha256(b'value=1\n').hexdigest()})
