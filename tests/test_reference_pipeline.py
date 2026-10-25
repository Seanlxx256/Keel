import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from keel.reference_pipeline import recover_pipeline
from tests import test_reference_network_recovery as fixtures


class ReferencePipelineTests(unittest.TestCase):
    def test_discovery_selects_only_verified_matching_assets_and_still_regrades(self):
        import hashlib
        from tests.test_apt_archive_bridge import artifact
        from examples.check_repository_network import extract_apt
        for kind in ('valid','changed-image','foreign-task','changed-policy','tampered-report'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);task,export,failed=fixtures.ReferenceNetworkRecoveryTests().fixture(root)
                parent=root/'evidence';accepted=parent/'accepted'
                self.write_grade(accepted,failed,'graded',True)
                script=next(failed.rglob('setup_repo.sh'))
                a=artifact(extract_apt(script.read_text()))
                (accepted/'apt-archives.json').write_text(json.dumps(a))
                (accepted/'network-policy.json').write_text(json.dumps({'policy':'retry_acquire','version':1}))
                report=accepted/'logs/run_evaluation/run/model/org__lib-1/report.json';report.parent.mkdir(parents=True)
                report.write_text(json.dumps({'org__lib-1':{'resolved':True}}))
                p=accepted/'grading.json';g=json.loads(p.read_text())
                g.update(network_policy='retry_acquire',network_policy_sha256=hashlib.sha256((accepted/'network-policy.json').read_bytes()).hexdigest(),
                    apt_archives_sha256=hashlib.sha256((accepted/'apt-archives.json').read_bytes()).hexdigest(),
                    report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),instance_cache={'scope':'b'*32,'cache_level':'instance'})
                p.write_text(json.dumps(g))
                build=accepted/'logs/build_images/instances/sweb.eval.x86_64.org__lib-1__fixture';build.mkdir(parents=True)
                (build/'Dockerfile').write_text('FROM '+a['base_image']+'\n')
                (build/'build_image.log').write_text('Successfully built '+'d'*12+'\nImage built successfully!\n')
                def inspect_image(name,seconds):
                    if kind=='changed-image':return 'sha256:'+'e'*64
                    if name==a['base_image']:return a['base_image_id']
                    if name==a['image']:return a['image_id']
                    return 'sha256:'+'d'*64
                if kind=='foreign-task':(accepted/'grader-input.json').write_text('[]')
                if kind=='changed-policy':(accepted/'network-policy.json').write_text('{}')
                if kind=='tampered-report':report.write_text('{}')
                calls=[]
                def grade(t,e,out,**kwargs):
                    calls.append(kwargs)
                    self.assertEqual(kwargs['instance_cache_scope'],'b'*32)
                    self.assertEqual(Path(kwargs['apt_archives']),accepted/'apt-archives.json')
                    self.write_grade(out,failed,'graded',True)
                result=recover_pipeline(task,export,failed,root/'out',python='python',grader=grade,
                    preparation_roots=[parent],cache_inspector=inspect_image)
                if kind=='valid':
                    self.assertEqual(result['status'],'reference_verified',result)
                    self.assertEqual(len(calls),1)  # Prior acceptance is not the new result.
                    self.assertEqual(result['preparation_discovery']['selected']['grade'],str(accepted))
                    report.write_text('{}')
                    with self.assertRaisesRegex(ValueError,'artifact changed'):
                        recover_pipeline(task,export,failed,root/'out',python='python',resume=True,preparation_roots=[parent])
                else:
                    self.assertEqual(result['status'],'environment_unresolved')
                    self.assertEqual(calls,[])

    def test_archive_and_build_cache_reuse_are_bound_and_forwarded_without_diagnosis(self):
        from tests.test_apt_archive_bridge import artifact
        from examples.check_repository_network import extract_apt
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=fixtures.ReferenceNetworkRecoveryTests().fixture(root)
            script=next(failed.rglob('setup_repo.sh'));value=artifact(extract_apt(script.read_text()))
            dockerfile=next(failed.rglob('Dockerfile'))
            value['base_image']=dockerfile.read_text().split()[-1]
            path=root/'artifact.json';path.write_text(json.dumps(value));calls=[]
            def grade(t,e,out,**kwargs):
                calls.append(kwargs)
                self.assertEqual(kwargs['apt_archives'],str(path.resolve()))
                self.assertEqual(kwargs['instance_cache_scope'],'a'*32)
                self.assertEqual(kwargs['network_policy'],'retry_acquire')
                self.write_grade(out,failed,'graded',True)
            result=recover_pipeline(task,export,failed,root/'out',python='python',grader=grade,
                apt_archives=path,instance_cache_scope='a'*32)
            self.assertEqual(result['status'],'reference_verified')
            self.assertEqual([s['action'] for s in result['stages']],['apt_retry'])
            self.assertEqual(len(calls),1)
            path.write_text(json.dumps({**value,'apt_command_sha256':'0'*64}))
            with self.assertRaisesRegex(ValueError,'drift'):
                recover_pipeline(task,export,failed,root/'out',python='python',grader=Mock(),
                    apt_archives=path,instance_cache_scope='a'*32,resume=True)
            grader=Mock()
            rejected=recover_pipeline(task,export,failed,root/'bad',python='python',grader=grader,apt_archives=path)
            self.assertIn('does not match',rejected['error'])
            grader.assert_not_called()

    def setup_case(self,root):
        task,export,failed=fixtures.ReferenceNetworkRecoveryTests().fixture(root)
        # Enter via a real test-failure record, with an archived instance recipe.
        p=failed/'grading.json';v=json.loads(p.read_text());v.update(status='graded',official_resolved=False)
        p.write_text(json.dumps(v))
        return task,export,failed

    def write_grade(self,directory,source,status,resolved):
        directory.mkdir(parents=True)
        (directory/'grader-input.json').write_bytes((source/'grader-input.json').read_bytes())
        (directory/'grading.json').write_text(json.dumps({'runtime_status':'reference_only',
            'status':status,'official_resolved':resolved}))

    def test_compatibility_network_acceptance_automatically_chains_and_reuses_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=self.setup_case(root);calls=[]
            def compat(t,e,f,out,**kwargs):
                calls.append(('compat',kwargs['timeout']))
                target=out/'reference-grade'
                self.write_grade(target,failed,'grading_error',None)
                build=target/'logs/build_images/instances/sweb.eval.x86_64.org__lib-1__adapted'
                build.mkdir(parents=True)
                original=next((failed/'logs/build_images/instances').iterdir())
                for name in ('Dockerfile','setup_repo.sh','build_image.log'):
                    (build/name).write_bytes((original/name).read_bytes())
                (out/'recovery.json').write_text('{}')
            def grade(t,e,out,**kwargs):
                calls.append(('retry',kwargs['timeout']))
                self.assertEqual(kwargs['network_policy'],'retry_acquire')
                self.write_grade(out,failed,'graded',True)
            result=recover_pipeline(task,export,failed,root/'out',python='python',timeout=300,
                                    compatibility=compat,grader=grade)
            self.assertEqual(result['status'],'reference_verified')
            self.assertEqual([s['action'] for s in result['stages']],['compatibility','apt_retry'])
            self.assertLessEqual(calls[1][1],calls[0][1]+1)
            later=recover_pipeline(task,export,failed,root/'out',python='python',timeout=300,
                                   compatibility=Mock(side_effect=AssertionError),grader=Mock(side_effect=AssertionError),resume=True)
            self.assertEqual(result,later)

    def test_unsupported_signature_never_dispatches_or_drops_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=fixtures.ReferenceNetworkRecoveryTests().fixture(root)
            log=next(failed.rglob('build_image.log'));log.write_text('E: NO_PUBKEY broken\n')
            grade=Mock()
            result=recover_pipeline(task,export,failed,root/'out',python='python',grader=grade)
            self.assertEqual(result['status'],'environment_unresolved')
            self.assertEqual(result['stages'],[])
            grade.assert_not_called()

    def test_interrupted_stage_cannot_be_repeated_on_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=self.setup_case(root)
            result=recover_pipeline(task,export,failed,root/'out',python='python',
                compatibility=Mock(side_effect=RuntimeError('launcher failed')))
            self.assertEqual(result['stages'][0]['status'],'running')
            with self.assertRaisesRegex(ValueError,'Interrupted'):
                recover_pipeline(task,export,failed,root/'out',python='python',resume=True)

    def test_completed_artifact_tampering_rejected_without_regrading(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=fixtures.ReferenceNetworkRecoveryTests().fixture(root)
            def grade(t,e,out,**kwargs):self.write_grade(out,failed,'graded',True)
            result=recover_pipeline(task,export,failed,root/'out',python='python',grader=grade)
            target=Path(result['reference_grade'])/'grading.json';target.write_text('{}')
            with self.assertRaisesRegex(ValueError,'artifact changed'):
                recover_pipeline(task,export,failed,root/'out',python='python',resume=True)

    def test_completed_cold_build_is_reused_once_without_rebuilding(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=fixtures.ReferenceNetworkRecoveryTests().fixture(root)
            p=failed/'grading.json';v=json.loads(p.read_text());v['error']='TimeoutExpired: total deadline';p.write_text(json.dumps(v))
            log=next(failed.rglob('build_image.log'))
            log.write_text('Successfully built '+ 'b'*12+'\nImage built successfully!\n')
            def grade(t,e,out,**kwargs):
                self.assertLessEqual(kwargs['timeout'],600)
                self.write_grade(out,failed,'graded',True)
            result=recover_pipeline(task,export,failed,root/'out',python='python',grader=grade,
                                    cache_inspector=lambda *a:'sha256:'+'b'*64)
            self.assertEqual(result['status'],'reference_verified')
            self.assertEqual(result['stages'][0]['action'],'cached_regrade')

    def test_missing_completed_image_never_dispatches_a_cold_rebuild(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=fixtures.ReferenceNetworkRecoveryTests().fixture(root)
            p=failed/'grading.json';v=json.loads(p.read_text());v['error']='TimeoutExpired';p.write_text(json.dumps(v))
            next(failed.rglob('build_image.log')).write_text('Successfully built '+ 'b'*12+'\nImage built successfully!\n')
            grader=Mock()
            result=recover_pipeline(task,export,failed,root/'out',python='python',grader=grader,
                                    cache_inspector=lambda *a:'sha256:'+'c'*64)
            self.assertEqual(result['status'],'environment_unresolved')
            grader.assert_not_called()

    def test_stage_transition_does_not_reset_wallclock_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=self.setup_case(root);clock=[0]
            def compat(t,e,f,out,**kwargs):
                target=out/'reference-grade';self.write_grade(target,failed,'grading_error',None)
                original=next((failed/'logs/build_images/instances').iterdir())
                build=target/'logs/build_images/instances'/original.name;build.mkdir(parents=True)
                for name in ('Dockerfile','setup_repo.sh','build_image.log'):
                    (build/name).write_bytes((original/name).read_bytes())
                clock[0]=240
            def grade(t,e,out,**kwargs):
                self.assertEqual(kwargs['timeout'],60)
                self.write_grade(out,failed,'graded',True)
            with patch('keel.reference_pipeline.time.monotonic',side_effect=lambda:clock[0]):
                result=recover_pipeline(task,export,failed,root/'out',python='python',timeout=300,
                    compatibility=compat,grader=grade)
            self.assertEqual(result['seconds'],240)
            self.assertEqual(result['status'],'reference_verified')
