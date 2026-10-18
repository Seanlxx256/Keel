import importlib.util
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from examples.launch_serena import prepare


@unittest.skipUnless(importlib.util.find_spec('serena'), 'Run with the isolated Serena Python')
class SerenaMetadataIsolationTests(unittest.TestCase):
    def test_real_serena_config_relocates_metadata_preserves_source_and_separates_workspaces(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ):
            root = Path(temp)
            homes = []
            for parent in ('first', 'second'):
                repo = root / parent / 'repo'
                repo.mkdir(parents=True)
                (repo/'module.py').write_text('def version(): return 1\n', encoding='utf-8')
                (repo/'.serena').mkdir()
                (repo/'.serena/project.yml').write_text('# existing repository metadata\n', encoding='utf-8')
                before = {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob('*') if p.is_file()}
                program = ('from examples.launch_serena import prepare; import sys; '
                           'a=prepare(sys.argv[1],sys.argv[2]); '
                           'assert prepare(sys.argv[1],sys.argv[2]) == a; '
                           'from serena.config.serena_config import SerenaConfig,ProjectConfig; '
                           'from serena.project import Project; c=SerenaConfig.from_config_file(); '
                           'p=ProjectConfig.load(sys.argv[1],serena_config=c); '
                           'Project(project_root=sys.argv[1],project_config=p,serena_config=c); print(a)')
                child = subprocess.run([sys.executable, '-c', program, str(repo), str(root/'external')],
                                       capture_output=True, text=True, encoding='utf-8', timeout=30)
                self.assertEqual(child.returncode, 0, child.stderr)
                home = Path(child.stdout.strip())
                self.assertEqual(before, {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob('*') if p.is_file()})
                from ruamel.yaml import YAML
                config = YAML().load((home/'project-data/project.yml').read_text(encoding='utf-8'))
                self.assertTrue(config['read_only'])
                self.assertTrue(config['language_servers'])
                self.assertTrue((home/'project-data/.gitignore').is_file())
                homes.append(home)
            self.assertNotEqual(*homes)
