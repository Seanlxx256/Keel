from types import SimpleNamespace
import unittest
from keel.harness_network import apply_network_policy


class HarnessNetworkTests(unittest.TestCase):
    def test_policy_preserves_commands_tests_and_source_identity(self):
        original=['git reset --hard original','apt-get -y update && apt-get install -y texlive','python -m pip install -e .']
        spec=SimpleNamespace(repo_script_list=list(original),eval_script_list=['pytest test.py'],
            env_script_list=['conda activate testbed'],instance_image_tag='latest',base_commit='original')
        apply_network_policy(spec,'no_pipeline')
        for line in original:
            self.assertIn(line,spec.repo_script_list)
        self.assertEqual(spec.eval_script_list,['pytest test.py'])
        self.assertEqual(spec.env_script_list,['conda activate testbed'])
        self.assertEqual(spec.base_commit,'original')
        self.assertNotEqual(spec.instance_image_tag,'latest')
        self.assertIn('Pipeline-Depth', '\n'.join(spec.repo_script_list))
        previous=list(spec.repo_script_list)
        apply_network_policy(spec,'no_pipeline')
        self.assertEqual(spec.repo_script_list,previous)

    def test_unsupported_policy_or_installer_stops(self):
        spec=SimpleNamespace(repo_script_list=['pip install .'])
        for policy in ('arbitrary','no_pipeline'):
            with self.assertRaises(ValueError):
                apply_network_policy(spec,policy)
