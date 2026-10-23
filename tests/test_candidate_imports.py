from contextlib import contextmanager
from contextlib import redirect_stdout
import base64
import io
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from keel.candidate_imports import candidate_context, module_manifest


class CandidateImportTests(unittest.TestCase):
    def test_partial_snapshot_cannot_shadow_editable_package_parent(self):
        with self.fixture() as (snapshot,current):
            installed=snapshot.parent/'installed'
            (installed/'probe_fixture_package/__init__.py').write_text(
                'configuration="real"\nfrom .api import value\n',encoding='utf-8')
            (current/'api.py').write_text('from . import configuration\nfrom .helper import suffix\n'
                                        'def value(): return configuration+suffix\n',encoding='utf-8')
            # PEP 660-style editable finder after PathFinder. A partial cwd
            # namespace must not win before this provider can load package init.
            class EditableFinder:
                @staticmethod
                def find_spec(fullname,path=None,target=None):
                    if fullname=='probe_fixture_package':
                        return importlib.machinery.PathFinder.find_spec(fullname,[str(installed)])
                    return None
            paths=list(sys.path);sys.path.remove(str(installed));sys.path.insert(0,str(snapshot))
            sys.meta_path.append(EditableFinder)
            try:
                mapping=module_manifest(snapshot,['probe_fixture_package/api.py'])
                with candidate_context(snapshot,mapping):
                    package=importlib.import_module('probe_fixture_package')
                    self.assertEqual(package.value(),'real:dependency')
                    self.assertEqual(package.configuration,'real')
                self.assertIn(str(snapshot),sys.path)
            finally:
                sys.meta_path.remove(EditableFinder);sys.path[:]=paths

    def test_actual_probe_worker_wraps_trusted_fixture_with_qualified_candidate_import(self):
        from keel.diagnostic_probe import BOOTSTRAP
        import keel.candidate_imports as implementation
        # Execute only a developer-authored fixture in a local child. Production
        # model code remains Docker-only; kernel file limits are mocked here.
        with self.fixture() as (snapshot,current):
            installed=snapshot.parent/'installed'
            code=f'import sys; sys.path.insert(0,{str(installed)!r})\nimport probe_fixture_package\nprint(probe_fixture_package.value())'
            context={'root':str(snapshot),'modules':module_manifest(snapshot,['probe_fixture_package/api.py']),
                     'helper':Path(implementation.__file__).read_text(encoding='utf-8')}
            argv=['bootstrap',base64.b64encode(code.encode()).decode(),
                  base64.b64encode(json.dumps(context).encode()).decode()]
            real_run=subprocess.run
            def trusted_child(command,**kwargs):
                completed=real_run(command,capture_output=True,timeout=10)
                kwargs['stdout'].write(completed.stdout);kwargs['stderr'].write(completed.stderr)
                return completed
            capture=io.StringIO()
            with patch.object(sys,'argv',argv), patch.dict(sys.modules,{
                    'resource':SimpleNamespace(RLIMIT_FSIZE=1,setrlimit=lambda *args:None)}), patch(
                    'subprocess.run',side_effect=trusted_child), redirect_stdout(capture):
                exec(BOOTSTRAP,{'__name__':'__main__'})
            result=json.loads(capture.getvalue())
            self.assertEqual(result['returncode'],0,result['stderr'])
            self.assertEqual(result['stdout'].strip(),'candidate:dependency')
            self.assertIn('__KEEL_CANDIDATE_IMPORTS__',result['stderr'])
            self.assertIn(context['modules']['probe_fixture_package.api']['sha256'],result['stderr'])

    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);installed=root/'installed';snapshot=root/'snapshot'
            package=installed/'probe_fixture_package';package.mkdir(parents=True)
            current=snapshot/'probe_fixture_package';current.mkdir(parents=True)
            (package/'__init__.py').write_text('from .api import value\n',encoding='utf-8')
            (package/'api.py').write_text('from .helper import suffix\ndef value(): return "base"+suffix\n',encoding='utf-8')
            (package/'helper.py').write_text('suffix = ":dependency"\n',encoding='utf-8')
            (current/'api.py').write_text('from .helper import suffix\ndef value(): return "candidate"+suffix\n',encoding='utf-8')
            sys.path.insert(0,str(installed));importlib.invalidate_caches()
            try:yield snapshot,current
            finally:
                sys.path.remove(str(installed))
                for name in list(sys.modules):
                    if name.startswith('probe_fixture_package'):del sys.modules[name]

    def test_normal_import_preserves_relative_dependencies_and_eager_reexports(self):
        with self.fixture() as (snapshot,current):
            before=(current/'api.py').read_bytes()
            mapping=module_manifest(snapshot,['probe_fixture_package/api.py'])
            with candidate_context(snapshot,mapping) as loaded:
                package=importlib.import_module('probe_fixture_package')
                self.assertEqual(package.value(),'candidate:dependency')
                self.assertEqual(package.value.__module__,'probe_fixture_package.api')
                self.assertEqual(loaded[0]['sha256'],mapping['probe_fixture_package.api']['sha256'])
                self.assertEqual(loaded[0]['status'],'executed')
                self.assertEqual(Path(sys.modules['probe_fixture_package.api'].__file__),current/'api.py')
            self.assertNotIn('probe_fixture_package',sys.modules)
            self.assertEqual(before,(current/'api.py').read_bytes())

    def test_candidate_package_init_keeps_installed_dependency_search_path(self):
        with self.fixture() as (snapshot,current):
            (current/'__init__.py').write_text('from .api import value\norigin="candidate init"\n',encoding='utf-8')
            mapping=module_manifest(snapshot,['probe_fixture_package/__init__.py','probe_fixture_package/api.py'])
            with candidate_context(snapshot,mapping):
                package=importlib.import_module('probe_fixture_package')
                self.assertEqual(package.origin,'candidate init')
                self.assertEqual(package.value(),'candidate:dependency')

    def test_changed_candidate_hash_fails_instead_of_importing_stale_source(self):
        with self.fixture() as (snapshot,current):
            mapping=module_manifest(snapshot,['probe_fixture_package/api.py'])
            (current/'api.py').write_text('raise AssertionError("must not execute")',encoding='utf-8')
            with candidate_context(snapshot,mapping):
                with self.assertRaisesRegex(RuntimeError,'hash changed'):
                    importlib.import_module('probe_fixture_package')

    def test_preimported_package_is_rejected_instead_of_mixing_cached_classes(self):
        with self.fixture() as (snapshot,current):
            original=importlib.import_module('probe_fixture_package')
            mapping=module_manifest(snapshot,['probe_fixture_package/api.py'])
            with self.assertRaisesRegex(RuntimeError,'already imported'):
                with candidate_context(snapshot,mapping):pass
            self.assertIs(sys.modules['probe_fixture_package'],original)

    def test_snapshot_escape_is_rejected(self):
        with self.fixture() as (snapshot,current):
            with self.assertRaisesRegex(ValueError,'escapes'):
                module_manifest(snapshot,['../installed/probe_fixture_package/api.py'])
