import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from keel.network_recovery import recover_network


class NetworkRecoveryTests(unittest.TestCase):
    def test_failed_recovery_returns_real_log_and_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as temp:
            previous,script,output=self.fixture(Path(temp))
            model=SimpleNamespace(complete_json=unittest.mock.Mock(side_effect=[
                self.reply('probe_http'),self.reply('apt_no_pipeline',['observation-1']),self.reply('stop',['observation-2'])]))
            def failed(script,image,directory,*args,**kwargs):
                (directory/'apt-build-attempt-1.log').write_text('E: Failed to fetch http://example.com/a.deb 502 Bad Gateway')
                return {'status':'apt_failed'}
            with patch('keel.network_recovery.build_probe',return_value={
                    'status':'completed','observation':{'download_complete':True}}):
                report=recover_network(previous,script,'local:test',output,model,failed)
            prompt=json.loads(model.complete_json.call_args_list[2].args[0][-1]['content'])
            self.assertIn('502 Bad Gateway',str(prompt['observations']['observation-2']['failure_feedback']))
            self.assertNotIn('apt_no_pipeline',prompt['allowed_actions'])
            self.assertEqual(report['status'],'environment_unresolved')
            self.assertEqual(report['stop_reason'],'model_stopped')

    def test_verified_experience_requires_matching_base_and_fresh_probes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            previous,script,output=self.fixture(root)
            value=json.loads((previous/'diagnosis.json').read_text()); value['base_image_id']='sha256:'+'a'*64
            (previous/'diagnosis.json').write_text(json.dumps(value))
            def model():
                return SimpleNamespace(complete_json=unittest.mock.Mock(side_effect=[
                    self.reply('probe_http'),self.reply('apt_no_pipeline',['observation-1'])]))
            with patch('keel.network_recovery.build_probe',return_value={
                    'status':'completed','observation':{'download_complete':True}}):
                first=recover_network(previous,script,'local:test',output,model(),
                    unittest.mock.Mock(return_value={'status':'apt_completed','base_image_id':value['base_image_id']}))
                second_output=root/'second'; second_output.mkdir()
                second_model=SimpleNamespace(complete_json=unittest.mock.Mock(side_effect=[
                    self.reply('apt_no_pipeline'),self.reply('stop')]))
                workload=unittest.mock.Mock()
                second=recover_network(previous,script,'local:test',second_output,second_model,workload)
            self.assertEqual(first['status'],'apt_recovered_under_transport_policy')
            self.assertTrue(second['experience']['matched_verified_workload'])
            workload.assert_not_called()
            self.assertEqual(second['actions'][0]['status'],'invalid_action')

    def test_invalid_citation_is_corrected_using_explicit_feedback(self):
        with tempfile.TemporaryDirectory() as temp:
            previous,script,output=self.fixture(Path(temp))
            model=SimpleNamespace(complete_json=unittest.mock.Mock(side_effect=[
                self.reply('probe_http',['imaginary-probe']),self.reply('probe_http',['initial']),
                self.reply('apt_no_pipeline',['observation-2'])]))
            workload=unittest.mock.Mock(return_value={'status':'apt_completed'})
            with patch('keel.network_recovery.build_probe',return_value={
                    'status':'completed','observation':{'download_complete':True}}) as probe:
                report=recover_network(previous,script,'local:test',output,model,workload)
            self.assertEqual(probe.call_count,1)
            second=model.complete_json.call_args_list[1].args[0][-1]['content']
            self.assertIn('available_evidence_ids',second)
            self.assertIn('imaginary-probe',second)
            self.assertIn('No tool executed',second)
            self.assertEqual(report['status'],'apt_recovered_under_transport_policy')

    def test_latest_failed_stage_is_first_and_probe_cap_reserves_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            previous,script,output=self.fixture(Path(temp))
            latest='http://example.com/dists/latest/InRelease'
            (previous/'apt-build-attempt-3.log').write_text('E: Failed to fetch '+latest+' 502 Bad Gateway')
            model=SimpleNamespace(complete_json=unittest.mock.Mock(side_effect=[
                self.reply('probe_http'),self.reply('probe_https'),self.reply('probe_http'),self.reply('stop')]))
            with patch('keel.network_recovery.build_probe',return_value={
                    'status':'completed','observation':{'download_complete':True}}) as probe:
                report=recover_network(previous,script,'local:test',output,model,unittest.mock.Mock())
            self.assertEqual(report['urls'][0],latest)
            self.assertEqual(probe.call_args_list[0].args[1][0],latest)
            self.assertEqual(probe.call_count,2)
            prompt=json.loads(model.complete_json.call_args_list[2].args[0][-1]['content'])
            self.assertEqual(set(prompt['allowed_actions']),{'stop','apt_no_pipeline'})
            self.assertEqual(report['actions'][2]['status'],'invalid_action')

    def fixture(self, root):
        previous=root/'previous'; previous.mkdir()
        script=root/'setup.sh'; script.write_bytes(b'original setup')
        (previous/'diagnosis.json').write_text(json.dumps({'status':'apt_failed','image':'local:test',
            'source_sha256':hashlib.sha256(script.read_bytes()).hexdigest()}))
        (previous/'apt-build-attempt-1.log').write_text('E: Failed to fetch http://example.com/a.deb 502 Bad Gateway')
        output=root/'output'; output.mkdir()
        return previous,script,output

    def reply(self, action, evidence=()):
        return SimpleNamespace(tokens=100,content=json.dumps({'action':action,'url_index':0,
            'evidence_ids':list(evidence),'hypothesis':'inspect transport','reason':'observed fetch error','next_check':'validate workload'}))

    def test_observation_drives_next_action_and_recovery_requires_workload(self):
        with tempfile.TemporaryDirectory() as temp:
            previous,script,output=self.fixture(Path(temp))
            model=SimpleNamespace(complete_json=unittest.mock.Mock(side_effect=[
                self.reply('probe_http'),self.reply('probe_https',['observation-1']),
                self.reply('apt_no_pipeline',['observation-2'])]))
            workload=unittest.mock.Mock(return_value={'status':'apt_completed'})
            with patch('keel.network_recovery.build_probe', side_effect=[
                    {'status':'completed','observation':{'download_complete':False}},
                    {'status':'completed','observation':{'download_complete':True}}]):
                report=recover_network(previous,script,'local:test',output,model,workload)
            self.assertEqual(report['status'],'apt_recovered_under_transport_policy')
            self.assertEqual(report['budget']['model_calls'],3)
            self.assertIn('observation-1',str(model.complete_json.call_args_list[1]))
            self.assertEqual(workload.call_args.kwargs['transport'],'no_pipeline')

    def test_no_evidence_or_arbitrary_actions_cannot_execute_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            previous,script,output=self.fixture(Path(temp))
            model=SimpleNamespace(complete_json=unittest.mock.Mock(side_effect=[
                self.reply('apt_no_pipeline'),self.reply('shell'),self.reply('stop')]))
            workload=unittest.mock.Mock()
            report=recover_network(previous,script,'local:test',output,model,workload)
            workload.assert_not_called()
            self.assertEqual(report['status'],'environment_unresolved')
            self.assertEqual([r['status'] for r in report['actions']],['invalid_action','invalid_action','model_stopped'])

    def test_successful_probe_alone_is_not_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            previous,script,output=self.fixture(Path(temp))
            model=SimpleNamespace(complete_json=unittest.mock.Mock(side_effect=[self.reply('probe_https'),self.reply('stop'),self.reply('stop')]))
            with patch('keel.network_recovery.build_probe',return_value={
                    'status':'completed','observation':{'download_complete':True}}):
                report=recover_network(previous,script,'local:test',output,model,unittest.mock.Mock())
            self.assertEqual(report['status'],'environment_unresolved')
            self.assertEqual(report['actions'][1]['status'],'stop_review_requested')
            self.assertEqual(report['actions'][2]['status'],'model_stopped')

    def test_premature_stop_review_can_lead_to_validated_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            previous,script,output=self.fixture(Path(temp))
            model=SimpleNamespace(complete_json=unittest.mock.Mock(side_effect=[
                self.reply('probe_http'),self.reply('stop'),self.reply('apt_no_pipeline',['observation-1'])]))
            workload=unittest.mock.Mock(return_value={'status':'apt_completed'})
            with patch('keel.network_recovery.build_probe',return_value={
                    'status':'completed','observation':{'download_complete':True}}):
                report=recover_network(previous,script,'local:test',output,model,workload)
            prompt=model.complete_json.call_args_list[2].args[0][-1]['content']
            self.assertIn('stop-review-2',prompt)
            self.assertEqual(report['status'],'apt_recovered_under_transport_policy')
            self.assertEqual(report['budget']['model_calls'],3)
            workload.assert_called_once()
