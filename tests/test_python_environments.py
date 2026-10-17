import contextlib
import importlib.metadata
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from keel.task_factory import build_environment, construct, environment_spec, installed_versions, unsupported_transition, validate_recipe, lock_python_recipe
from keel.core import Budget, Limits
from examples.run_autonomous_campaign import solver_config


class PythonEnvironmentTests(unittest.TestCase):
    def recipe(self):
        return {'kind': 'python', 'python': '3.12', 'old': '3.11', 'new': '3.12',
                'common': ['pytest==7.4.4', 'pip==24.0', 'setuptools==68.2.2', 'wheel==0.41.3']}

    def test_python_task_is_supported_and_phase_specs_keep_dependencies_identical(self):
        self.assertIsNone(unsupported_transition('Python 3.12 compatibility'))
        self.assertIsNotNone(unsupported_transition('PyPy 7.3 compatibility'))
        old, old_pins = environment_spec(self.recipe(), 'old')
        new, new_pins = environment_spec(self.recipe(), 'new')
        self.assertEqual((old, new), ('3.11', '3.12'))
        self.assertEqual(old_pins, new_pins)

    def test_python_recipe_rejects_mixed_axes_and_invalid_versions(self):
        for changes in ({'new': 'urllib3==2.0'}, {'old': '3.12'}, {'python': '3.11'}, {'old': ['3.11']},
                        {'common': ['pytest==7.4.4']}, {'new': '3.12\nRUN bad'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_recipe({**self.recipe(), **changes})

    def test_builds_different_python_images_with_byte_identical_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def build(argv, directory, timeout, log):
                (directory/'image.id').write_text('sha256:'+'a'*64)
                return {'returncode': 0, 'timeout': False}
            with patch('keel.task_factory.command', side_effect=build):
                for phase in ('old', 'new'):
                    build_environment(self.recipe(), phase, root/phase, 10)
            self.assertIn('FROM python:3.11-slim', (root/'old/Dockerfile').read_text())
            self.assertIn('FROM python:3.12-slim', (root/'new/Dockerfile').read_text())
            self.assertEqual((root/'old/requirements.txt').read_bytes(), (root/'new/requirements.txt').read_bytes())

    def execute_inventory_script(self, runtime, extra=False):
        expected = dict(pin.split('==') for pin in self.recipe()['common'])
        distributions = [SimpleNamespace(metadata={'Name': name}, version=value) for name, value in expected.items()]
        if extra:
            distributions.append(SimpleNamespace(metadata={'Name': 'unexpected'}, version='1.0'))
        def run(command, *args, **kwargs):
            stream = io.StringIO()
            with patch.object(sys, 'argv', ['-c', *command[3:]]), \
                 patch.object(sys, 'version_info', (*runtime, 0)), \
                 patch('importlib.metadata.version', side_effect=lambda name: expected[name]), \
                 patch('importlib.metadata.distributions', return_value=distributions), contextlib.redirect_stdout(stream):
                try:
                    exec(command[2], {})
                except SystemExit as error:
                    return {'returncode': error.code, 'timeout': False, 'stdout': stream.getvalue(), 'stderr': ''}
        return run

    def test_inventory_verifies_actual_python_not_only_dependency_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('keel.task_factory.CommandRunner.run', side_effect=self.execute_inventory_script((3, 12))):
                result = installed_versions('image', self.recipe(), 'new', Path(temp), 5)
            self.assertEqual(result['packages']['pytest'], '7.4.4')
            with patch('keel.task_factory.CommandRunner.run', side_effect=self.execute_inventory_script((3, 11))):
                with self.assertRaises(ValueError):
                    installed_versions('image', self.recipe(), 'new', Path(temp), 5)

    def test_unpinned_extra_distribution_is_not_a_clean_python_only_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('keel.task_factory.CommandRunner.run', side_effect=self.execute_inventory_script((3, 12), extra=True)):
                with self.assertRaises(ValueError):
                    installed_versions('image', self.recipe(), 'new', Path(temp), 5)

    def test_solver_goal_names_python_instead_of_a_fictitious_package(self):
        factory = {'candidate': {'title': 'Runtime compatibility'}, 'recipe': self.recipe(),
                   'images': {'new': 'image'}, 'attempts': [{'cells': {'base_new': {'stdout': 'observed error'}}}]}
        config = solver_config({}, factory, ['tests'], Budget(Limits()), 24000)
        self.assertIn('Restore compatibility with Python 3.12', config['goal'])

    def test_resolver_build_and_inventory_lock_preserve_python_only_axis(self):
        recipe = {**self.recipe(), 'resolve_dependencies': True}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def build(argv, directory, timeout, log):
                (directory/'image.id').write_text('sha256:'+'a'*64)
                return {'returncode': 0, 'timeout': False}
            with patch('keel.task_factory.command', side_effect=build):
                build_environment(recipe, 'new', root/'image', 10)
            self.assertNotIn('--no-deps', (root/'image/Dockerfile').read_text())
        pins = dict(pin.split('==') for pin in recipe['common'])
        pins['transitive-package'] = '1.2.3'
        locked = lock_python_recipe(recipe, {'old': {'inventory': pins}, 'new': {'inventory': pins}})
        self.assertIn('transitive-package==1.2.3', locked['common'])
        self.assertNotIn('resolve_dependencies', locked)
        with self.assertRaisesRegex(ValueError, 'differ in dependencies'):
            lock_python_recipe(recipe, {'old': {'inventory': pins},
                                        'new': {'inventory': {**pins, 'transitive-package': '2.0'}}})

    def test_resolver_inventory_allows_transitives_but_still_checks_direct_pins_and_python(self):
        recipe = {**self.recipe(), 'resolve_dependencies': True}
        with tempfile.TemporaryDirectory() as temp:
            with patch('keel.task_factory.CommandRunner.run', side_effect=self.execute_inventory_script((3, 12), extra=True)):
                actual = installed_versions('image', recipe, 'new', Path(temp), 5)
            self.assertIn('unexpected', actual['inventory'])
            with patch('keel.task_factory.CommandRunner.run', side_effect=self.execute_inventory_script((3, 11), extra=True)):
                with self.assertRaises(ValueError):
                    installed_versions('image', recipe, 'new', Path(temp), 5)
