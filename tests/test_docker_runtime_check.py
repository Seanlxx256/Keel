import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from examples.check_docker_runtime import check


class DockerRuntimeCheckTests(unittest.TestCase):
    def test_build_recipe_is_valid_network_disabled_and_image_identity_checked(self):
        def run(command,**kw):
            kw['log_path'].write_text(('sha256:'+'b'*64) if 'inspect' in command else 'ready')
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'result'
            with patch('examples.check_docker_runtime.run_harness',side_effect=run) as runner:
                result=check('local:test',out,timeout=10)
            self.assertEqual(result['status'],'passed')
            self.assertEqual(result['model_calls'],0)
            lines=(out/'context/Dockerfile').read_text().splitlines()
            self.assertEqual(json.loads(lines[1][4:])[:2],['python','-c'])
            build=next(c.args[0] for c in runner.call_args_list if 'build' in c.args[0])
            self.assertIn('--network=none',build)
            self.assertEqual(runner.call_count,5)

    def test_build_timeout_is_preserved_and_cleanup_is_bounded(self):
        def run(command,**kw):
            if 'build' in command:raise subprocess.TimeoutExpired(command,10)
            kw['log_path'].write_text('sha256:'+'b'*64)
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as temp:
            with patch('examples.check_docker_runtime.run_harness',side_effect=run) as runner:
                result=check('local:test',Path(temp)/'result',timeout=10)
            self.assertEqual(result['status'],'timed_out')
            self.assertEqual(result['stage'],'build')
            self.assertEqual(runner.call_args.kwargs['timeout'],5)
