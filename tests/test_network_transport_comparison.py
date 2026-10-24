import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from keel.network_recovery import failed_workload_inputs
from keel.network_transport_comparison import compare_transports


class NetworkTransportComparisonTests(unittest.TestCase):
    def fixture(self,root):
        previous=root/'previous';previous.mkdir()
        script=root/'setup.sh';script.write_bytes(b'original setup')
        identity='sha256:'+'a'*64
        (previous/'diagnosis.json').write_text(json.dumps({'status':'apt_failed','image':'fixture:latest',
            'source_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),'base_image_id':identity}))
        (previous/'apt-build-attempt-1.log').write_text(
            'Get:1 http://example.com/success.deb [10 kB]\n'
            'E: Failed to fetch http://example.com/first.deb Unable to connect\n'
            'E: Failed to fetch http://example.com/last%2b.deb Unable to connect\n')
        return previous,script,identity

    def test_selects_terminal_errors_in_latest_attempt_not_successes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);previous,script,_=self.fixture(root)
            _,_,_,urls=failed_workload_inputs(previous,script,'fixture:latest')
            self.assertEqual(urls,['http://example.com/last%2b.deb','http://example.com/first.deb'])

    def test_same_exact_path_pair_and_content_are_recorded_without_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);previous,script,identity=self.fixture(root)
            probe=Mock(side_effect=[{'status':'completed','base_image_id':identity,
                'observation':{'download_complete':False}}, {'status':'completed','base_image_id':identity,
                'observation':{'download_complete':True,'sha256':'x'}}])
            result=compare_transports(previous,script,'fixture:latest',root/'out',probe=probe,identity=lambda:identity)
            self.assertEqual(result['outcome'],'https_only')
            self.assertEqual(result['model_calls'],0)
            self.assertEqual([c.args[1][0] for c in probe.call_args_list],
                ['http://example.com/last%2b.deb','https://example.com/last%2b.deb'])
            self.assertTrue((root/'out/comparison.json').exists())

    def test_image_drift_rejects_before_any_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);previous,script,_=self.fixture(root);probe=Mock()
            result=compare_transports(previous,script,'fixture:latest',root/'out',probe=probe,
                                      identity=lambda:'sha256:'+'b'*64)
            self.assertEqual(result['status'],'comparison_error');probe.assert_not_called()

    def test_second_failure_preserves_first_paid_work_free_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);previous,script,identity=self.fixture(root)
            probe=Mock(side_effect=[{'status':'completed','base_image_id':identity,
                'observation':{'download_complete':True}},TimeoutError()])
            result=compare_transports(previous,script,'fixture:latest',root/'out',probe=probe,identity=lambda:identity)
            self.assertEqual(result['status'],'comparison_error')
            self.assertEqual(len(json.loads((root/'out/comparison.json').read_text())['observations']),1)

    def test_credentials_in_failed_url_rejected_before_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);previous,script,identity=self.fixture(root);probe=Mock()
            (previous/'apt-build-attempt-1.log').write_text('E: Failed to fetch http://u:p@example.com/a.deb 502')
            with self.assertRaises(ValueError):
                compare_transports(previous,script,'fixture:latest',root/'out',probe=probe,identity=lambda:identity)
            probe.assert_not_called();self.assertFalse((root/'out').exists())

    def test_missing_probe_identity_does_not_become_transport_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);previous,script,identity=self.fixture(root)
            result=compare_transports(previous,script,'fixture:latest',root/'out',
                probe=Mock(return_value={'status':'timeout'}),identity=lambda:identity)
            self.assertEqual(result['status'],'incomplete_identity_or_probe')
            self.assertNotIn('outcome',result)
