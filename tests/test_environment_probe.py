import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from keel.environment_probe import PROGRAM, inspect_image, validate_inspection


class EnvironmentProbeTests(unittest.TestCase):
    def test_fixed_program_observes_import_location_and_missing_distribution(self):
        result=subprocess.run([sys.executable,'-c',PROGRAM,json.dumps({'modules':['json'],
            'distributions':['keel_nonexistent_probe_package']})],capture_output=True,text=True,check=True)
        observed=json.loads(result.stdout)
        self.assertTrue(observed['modules']['json']['file'].endswith('__init__.py'))
        self.assertIn('error',observed['distributions']['keel_nonexistent_probe_package'])

    def test_inspection_is_sandboxed_and_container_cleanup_is_attempted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            image=root/'logs/build_images/instances/sweb.eval.org__lib-1__keel-env-hash'
            image.mkdir(parents=True);(image/'Dockerfile').write_text('FROM base')
            with patch('keel.environment_probe.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{}',stderr='')) as run:
                result=inspect_image(root,['json'],[])
            args=run.call_args_list[0].args[0]
            self.assertIn('--read-only',args)
            self.assertEqual(args[args.index('--network')+1],'none')
            self.assertNotIn('--volume',args)
            self.assertEqual(result['image'],'sweb.eval.org__lib-1:keel-env-hash')
            self.assertEqual(run.call_args_list[1].args[0][:3],['docker','rm','-f'])

    def test_inspection_rejects_commands_and_empty_requests(self):
        for modules,distributions in [(['os;echo'],[]),([],['pip==24']),([],[]),(['../file'],[])]:
            with self.assertRaises(ValueError):
                validate_inspection(modules,distributions)

    def test_missing_image_is_restored_from_archived_recipe_before_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            image=root/'logs/build_images/instances/sweb.eval.org__lib-1__latest'
            image.mkdir(parents=True);(image/'Dockerfile').write_text('FROM base')
            replies=[SimpleNamespace(returncode=125,stdout='',stderr='No such image'),
                     SimpleNamespace(returncode=0),SimpleNamespace(returncode=0,stdout='{}',stderr=''),
                     SimpleNamespace(returncode=0)]
            with patch('keel.environment_probe.subprocess.run',side_effect=replies) as run:
                result=inspect_image(root,['json'],[])
            self.assertTrue(result['restored_from_archived_recipe'])
            self.assertEqual(run.call_args_list[1].args[0][:3],['docker','build','--pull=false'])
            self.assertEqual(run.call_args_list[2].args[0][0:2],['docker','run'])

    def test_probe_timeout_still_cleans_up_its_own_container(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            image=root/'logs/build_images/instances/sweb.eval.org__lib-1__latest'
            image.mkdir(parents=True);(image/'Dockerfile').write_text('FROM base')
            with patch('keel.environment_probe.subprocess.run',side_effect=[
                subprocess.TimeoutExpired('probe',1),SimpleNamespace(returncode=0)]) as run:
                with self.assertRaises(subprocess.TimeoutExpired):
                    inspect_image(root,['json'],[])
            started=run.call_args_list[0].args[0]
            cleanup=run.call_args_list[1].args[0]
            self.assertEqual(cleanup[-1],started[started.index('--name')+1])
