import json
import hashlib
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from keel.reference_network_recovery import recover_reference_network,failure_inputs
from keel.swebench import prepare,reference_prediction


class ReferenceNetworkRecoveryTests(unittest.TestCase):
    def test_archive_bridge_reuses_completed_diagnosis_before_fresh_grading(self):
        from tests.test_apt_archive_bridge import artifact
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=self.fixture(root);grader=Mock(return_value={'status':'graded','official_resolved':True})
            script=next(failed.rglob('setup_repo.sh'))
            def workload(s,image,out,*a,**kwargs):
                result={'status':'apt_completed','source_sha256':hashlib.sha256(s.read_bytes()).hexdigest()}
                (out/'diagnosis.json').write_text(json.dumps(result))
                return result
            exporter=Mock(return_value={'status':'completed','artifact':artifact()})
            result=recover_reference_network(task,export,failed,root/'out',Mock(),python='python',
                workload=workload,grader=grader,image_identity=lambda _:'sha256:'+'b'*64,
                bridge_archives=True,archive_exporter=exporter)
            self.assertEqual(result['status'],'reference_verified_reconstructed')
            self.assertEqual(exporter.call_args.args[1],script)
            self.assertLessEqual(exporter.call_args.kwargs['timeout'],300)
            self.assertEqual(grader.call_args.kwargs['apt_archives'],artifact())

    def test_requested_archive_bridge_failure_does_not_silently_redownload(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=self.fixture(root);grader=Mock()
            def workload(s,image,out,*a,**kwargs):
                result={'status':'apt_completed','source_sha256':hashlib.sha256(s.read_bytes()).hexdigest()}
                (out/'diagnosis.json').write_text(json.dumps(result));return result
            result=recover_reference_network(task,export,failed,root/'out',Mock(),python='python',
                workload=workload,grader=grader,image_identity=lambda _:'sha256:'+'b'*64,
                bridge_archives=True,archive_exporter=Mock(return_value={'status':'unavailable'}))
            self.assertEqual(result['status'],'environment_unresolved')
            self.assertEqual(result['stop_reason'],'archive_export_unavailable_no_blind_redownload')
            grader.assert_not_called()

    def compatibility_fixture(self,root):
        task,export,failed=self.fixture(root)
        from keel.harness_plugins import POLICY
        plugin=failed/'plugin-policy.json';plugin.write_text(json.dumps({'policy':POLICY,'version':1}))
        compat=failed/'compatibility-policy.json'
        compat.write_text(json.dumps({'pins':{'consumer':'1.0'},'anchors':{'provider':'2.0'}}))
        old=json.loads((failed/'grading.json').read_text())
        old.update(plugin_policy=POLICY,plugin_policy_sha256=hashlib.sha256(plugin.read_bytes()).hexdigest(),
                   compatibility_policy_sha256=hashlib.sha256(compat.read_bytes()).hexdigest())
        (failed/'grading.json').write_text(json.dumps(old))
        return task,export,failed

    def test_network_revalidation_preserves_verified_compatibility(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=self.compatibility_fixture(root)
            grader=Mock(return_value={'status':'graded','official_resolved':True})
            model=Mock()
            result=recover_reference_network(task,export,failed,root/'out',model,python='python',
                workload=Mock(return_value={'status':'apt_completed'}),grader=grader,
                image_identity=lambda _: 'sha256:'+'b'*64,preserve_compatibility=True)
            self.assertEqual(result['status'],'reference_verified_reconstructed')
            self.assertEqual(grader.call_args.kwargs['plugin_policy'],'remove_unused_vcs_versioning')
            self.assertEqual(grader.call_args.kwargs['compatibility_policy'],
                json.loads((failed/'compatibility-policy.json').read_text()))
            self.assertIn(str(failed/'compatibility-policy.json'),result['original_inputs'])
            model.complete_json.assert_not_called()

    def test_preservation_requires_opt_in_and_unchanged_policy_receipts(self):
        for kind in ('no_opt_in','changed_policy','same_category'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);task,export,failed=self.compatibility_fixture(root)
                if kind=='changed_policy':(failed/'compatibility-policy.json').write_text('{}')
                if kind=='same_category':
                    old=json.loads((failed/'grading.json').read_text());old['network_policy']='no_pipeline'
                    (failed/'grading.json').write_text(json.dumps(old))
                with self.assertRaises(ValueError):
                    failure_inputs(task,export,failed,preserve_compatibility=kind!='no_opt_in')

    def fixture(self,root):
        row={'instance_id':'org__lib-1','repo':'org/lib','base_commit':'a'*40,'problem_statement':'issue','patch':'REFERENCE','test_patch':'TEST'}
        source=root/'data.jsonl';source.write_text(json.dumps(row))
        task=root/'task';export=root/'reference';failed=root/'failed'
        prepare(source,row['instance_id'],task);reference_prediction(task,export)
        failed.mkdir()
        (failed/'grading.json').write_text(json.dumps({'status':'grading_error','runtime_status':'reference_only','instance_cache':{'scope':'a'*32}}))
        (failed/'grader-input.json').write_text(json.dumps([row]))
        build=failed/'logs/build_images/instances/sweb.eval.x86_64.org__lib-1__latest';build.mkdir(parents=True)
        (build/'build_image.log').write_text('E: Failed to fetch http://archive.example/a.deb Unable to connect\nE: Unable to fetch some archives\n')
        (build/'Dockerfile').write_text('FROM --platform=linux/x86_64 sweb.env.py.x86_64.fixture:latest\n')
        (build/'setup_repo.sh').write_text('git reset --hard '+row['base_commit']+'\napt-get -y update && apt-get -y upgrade && DEBIAN_FRONTEND=noninteractive apt-get install -y unzip\n')
        return task,export,failed

    def invoke(self,root,*,workload=None,network=None,grader=None,identity=None):
        task,export,failed=self.fixture(root)
        workload=workload or Mock(return_value={'status':'apt_completed'})
        network=network or Mock()
        grader=grader or Mock(return_value={'status':'graded','official_resolved':True})
        result=recover_reference_network(task,export,failed,root/'recovery',Mock(),python='python',workload=workload,network_recover=network,grader=grader,image_identity=identity or (lambda _: 'sha256:'+'b'*64))
        return result,workload,network,grader

    def test_original_retry_recovery_needs_fresh_reference_grade_without_model(self):
        with tempfile.TemporaryDirectory() as temp:
            result,workload,network,grader=self.invoke(Path(temp))
            self.assertEqual(result['status'],'reference_verified')
            self.assertEqual(result['model_calls'],0);network.assert_not_called()
            self.assertEqual(workload.call_args.kwargs['transport'],'original')
            self.assertEqual(workload.call_args.kwargs['progress_budget']['soft_seconds'],600)
            self.assertLessEqual(workload.call_args.args[3],1800-660)
            self.assertGreater(workload.call_args.args[3],600)
            self.assertNotIn('network_policy',grader.call_args.kwargs)
            self.assertEqual(grader.call_args.kwargs['instance_cache_scope'],'a'*32)
            self.assertLessEqual(grader.call_args.kwargs['timeout'],1800)

    def test_failed_retry_automatically_enters_network_workflow_then_regrades(self):
        with tempfile.TemporaryDirectory() as temp:
            network=Mock(return_value={'status':'apt_recovered_under_transport_policy','budget':{'model_calls':3}})
            result,_,network,grader=self.invoke(Path(temp),workload=Mock(return_value={'status':'apt_failed'}),network=network)
            self.assertEqual(result['status'],'reference_verified_reconstructed')
            self.assertEqual(result['model_calls'],3)
            self.assertEqual(network.call_args.args[0],Path(temp)/'recovery/apt-original')
            self.assertEqual(grader.call_args.kwargs['network_policy'],'no_pipeline')
            self.assertLessEqual(network.call_args.kwargs['timeout'],900)

    def test_actual_network_loop_receives_failed_workload_and_drives_revalidation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=self.fixture(root)
            identity='sha256:'+'b'*64
            def workload(script,image,out,timeout,**kwargs):
                status='apt_failed' if kwargs['transport']=='original' else 'apt_completed'
                result={'status':status,'image':image,'base_image_id':identity,'source_sha256':hashlib.sha256(script.read_bytes()).hexdigest()}
                (out/'diagnosis.json').write_text(json.dumps(result))
                (out/'apt-build-attempt-1.log').write_text('E: Failed to fetch http://archive.example/a.deb Unable to connect')
                return result
            def reply(action,evidence):
                return SimpleNamespace(tokens=100,content=json.dumps({'action':action,'url_index':0,'evidence_ids':evidence,'hypothesis':'transport issue','reason':'observed acquisition failure','next_check':'run exact workload'}))
            model=Mock();model.complete_json.side_effect=[reply('probe_http',['initial']),reply('apt_no_pipeline',['observation-1'])]
            grader=Mock(return_value={'status':'graded','official_resolved':True})
            with patch('keel.network_recovery.build_probe',return_value={'status':'completed','observation':{'download_complete':True}}):
                result=recover_reference_network(task,export,failed,root/'out',model,python='python',workload=workload,grader=grader,image_identity=lambda _:identity)
            self.assertEqual(result['status'],'reference_verified_reconstructed')
            self.assertEqual(result['model_calls'],2)
            self.assertEqual(grader.call_args.kwargs['network_policy'],'no_pipeline')
            events=[json.loads(x)['event'] for x in (root/'out/model-transcript.jsonl').read_text().splitlines()]
            self.assertEqual(events,['request','response','request','response'])

    def test_probe_or_workload_success_alone_is_not_reference_success(self):
        with tempfile.TemporaryDirectory() as temp:
            result,_,_,grader=self.invoke(Path(temp),grader=Mock(return_value={'status':'graded','official_resolved':False}))
            self.assertEqual(result['status'],'environment_unresolved')
            grader.assert_called_once()

    def test_unresolved_diagnosis_never_grades_or_claims_success(self):
        with tempfile.TemporaryDirectory() as temp:
            result,_,_,grader=self.invoke(Path(temp),workload=Mock(return_value={'status':'apt_failed'}),network=Mock(return_value={'status':'environment_unresolved'}))
            self.assertEqual(result['status'],'environment_unresolved');grader.assert_not_called()

    def test_image_drift_stops_before_revalidation(self):
        with tempfile.TemporaryDirectory() as temp:
            identity=Mock(side_effect=['sha256:'+'b'*64,'sha256:'+'b'*64,'sha256:'+'c'*64])
            result,_,_,grader=self.invoke(Path(temp),identity=identity)
            self.assertEqual(result['status'],'environment_unresolved');grader.assert_not_called()

    def test_signature_errors_or_mismatched_task_rejected_before_tools(self):
        for kind in ('signature','task'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);task,export,failed=self.fixture(root)
                if kind=='signature':
                    log=next(failed.rglob('build_image.log'));log.write_text(log.read_text()+'E: NO_PUBKEY broken\n')
                else:(failed/'grader-input.json').write_text('[]')
                workload=Mock()
                with self.assertRaises(ValueError):
                    recover_reference_network(task,export,failed,root/'out',Mock(),python='python',workload=workload)
                workload.assert_not_called();self.assertFalse((root/'out').exists())

    def test_changed_export_during_workload_cannot_regrade(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def workload(*a,**k):
                (root/'reference/predictions.jsonl').write_text('{}')
                return {'status':'apt_completed'}
            result,_,_,grader=self.invoke(root,workload=workload)
            self.assertEqual(result['status'],'environment_unresolved');grader.assert_not_called()
