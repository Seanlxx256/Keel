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
