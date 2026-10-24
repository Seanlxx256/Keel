import hashlib
import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from examples.check_repository_network import apt_workload
from keel.apt_transport import transport_prefix,CACHE_PROBE
from keel.harness_network import apply_network_policy


class AptTransportTests(unittest.TestCase):
    def test_registered_retry_is_shared_with_grader_without_changing_commands(self):
        command='apt-get -y update && apt-get -y upgrade && apt-get install -y unzip'
        spec=SimpleNamespace(repo_script_list=[command],instance_image_tag='latest')
        apply_network_policy(spec,'retry_acquire')
        self.assertEqual(spec.repo_script_list[-1],command)
        self.assertEqual(spec.repo_script_list[:-1],transport_prefix('retry_acquire').splitlines())
        self.assertIn('Acquire::Retries "2";',transport_prefix('retry_acquire'))
        self.assertNotIn('Verify-Peer',transport_prefix('retry_acquire'))
        before=list(spec.repo_script_list)
        apply_network_policy(spec,'retry_acquire')
        self.assertEqual(before,spec.repo_script_list)
        with self.assertRaises(ValueError):apply_network_policy(spec,'no_pipeline')

    def test_transient_fetch_retries_preserve_cache_evidence_and_original_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);script=root/'setup.sh'
            command='apt-get -y update && apt-get -y upgrade && apt-get install -y unzip'
            script.write_text(command)
            output=root/'out';output.mkdir();calls=[]
            def harness(args,**kwargs):
                calls.append(args)
                context=Path(args[-1])
                generated=(context/'apt.sh').read_text()
                self.assertIn(command,generated)
                self.assertIn('Acquire::Retries "2";',generated)
                self.assertIn('exit "$status"',generated)
                self.assertIn('sharing=locked',(context/'Dockerfile').read_text())
                before={'phase':'before','files':[{'name':'cached.deb','bytes':10}]}
                after={'phase':'after','files':[{'name':'cached.deb','bytes':10},{'name':'new.deb','bytes':20}]}
                text='KEEL_APT_CACHE='+json.dumps(before)+'\nKEEL_APT_CACHE='+json.dumps(after)+'\n'
                if len(calls)==1:text+='E: Failed to fetch http://example.com/a.deb Unable to connect\n'
                kwargs['log_path'].write_text(text)
                return SimpleNamespace(returncode=1 if len(calls)==1 else 0)
            with patch('examples.check_repository_network.subprocess.run',return_value=SimpleNamespace(stdout='sha256:'+'a'*64)), \
                    patch('examples.check_repository_network.run_harness',side_effect=harness), \
                    patch('keel.network_probe.time.sleep'):
                result=apt_workload(script,'fixture:latest',output,120,attempts=2,transport='retry_acquire')
            self.assertEqual(result['status'],'apt_completed')
            self.assertEqual(len(result['attempts']),2)
            self.assertEqual(len(result['cache_observations']),4)
            self.assertEqual(result['archive_cache_id'],'keel-apt-'+hashlib.sha256(('sha256:'+'a'*64).encode()).hexdigest()[:24])

    def test_install_error_is_not_retried_and_missing_inventory_does_not_change_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);script=root/'setup.sh'
            script.write_text('apt-get -y update && apt-get -y upgrade && apt-get install -y unzip')
            output=root/'out';output.mkdir();calls=[]
            def harness(args,**kwargs):
                calls.append(args);kwargs['log_path'].write_text('E: Sub-process /usr/bin/dpkg returned an error code (1)\n')
                return SimpleNamespace(returncode=1)
            with patch('examples.check_repository_network.subprocess.run',return_value=SimpleNamespace(stdout='sha256:'+'a'*64)), \
                    patch('examples.check_repository_network.run_harness',side_effect=harness):
                result=apt_workload(script,'fixture:latest',output,120,attempts=2,transport='retry_acquire')
            self.assertEqual(len(calls),1)
            self.assertEqual(result['status'],'apt_failed')
            self.assertEqual(result['cache_observation_status'],'unavailable')

    def test_embedded_cache_probe_is_valid_python(self):
        compile(CACHE_PROBE,'cache_probe','exec')

    def test_failed_workload_cli_returns_failure_not_successful_dispatch(self):
        from examples.check_repository_network import main
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'out'
            argv=['probe','--apt-script','setup.sh','--image','fixture:latest','--output',str(output),
                  '--transport','retry_acquire','--progress-aware']
            with patch.object(sys,'argv',argv),patch('examples.check_repository_network.apt_workload',
                    return_value={'status':'apt_failed'}) as workload:
                self.assertEqual(main(),1)
            self.assertEqual(workload.call_args.kwargs['transport'],'retry_acquire')
            self.assertEqual(workload.call_args.kwargs['progress_budget']['soft_seconds'],600)

    def test_verified_reference_policy_roundtrip_keeps_explicit_identity(self):
        from examples.run_swebench_task import reference_policies
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);policy=root/'network-policy.json'
            policy.write_text(json.dumps({'policy':'retry_acquire','version':1}))
            (root/'grading.json').write_text(json.dumps({'network_policy':'retry_acquire',
                'network_policy_sha256':hashlib.sha256(policy.read_bytes()).hexdigest()}))
            self.assertEqual(reference_policies(root),{'network_policy':'retry_acquire'})
