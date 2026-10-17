import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from examples.run_factory_task import execute, load_factory
from keel.task_factory import inventory


class FactoryTaskTests(unittest.TestCase):
    def fixture(self, root):
        factory = root/'factory'
        for phase in ('base', 'gold'):
            source = factory/phase
            (source/'tests').mkdir(parents=True)
            (source/'tests/test_app.py').write_text('def test_app(): pass')
            (source/'app.py').write_text('VALUE = 1')
        frozen = {name: sha for name, sha in inventory(factory/'base').items() if name.startswith('tests/')}
        data = {'status': 'transition_verified', 'candidate': {'title': 'Compatibility'},
                'recipe': {'python': '3.11', 'common': ['pytest==7.4.4'], 'old': 'dep==1', 'new': 'dep==2'},
                'images': {'old': 'sha256:'+'a'*64, 'new': 'sha256:'+'b'*64},
                'test_roots': ['tests'], 'frozen_tests': frozen}
        (factory/'factory.json').write_text(json.dumps(data))
        return factory

    def test_added_or_modified_acceptance_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            factory = self.fixture(Path(temp))
            load_factory(factory)
            (factory/'base/tests/extra.py').write_text('pass')
            with self.assertRaisesRegex(ValueError, 'acceptance changed'):
                load_factory(factory)

    def test_failed_revalidation_spends_no_model_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            factory = self.fixture(root)
            with patch('examples.run_factory_task.from_config', return_value=Mock()), \
                 patch('examples.run_factory_task.installed_versions'), \
                 patch('examples.run_factory_task.probe', return_value={}), \
                 patch('examples.run_factory_task.run') as solve:
                with self.assertRaisesRegex(ValueError, 'three-cell'):
                    execute(factory, root/'trial', {})
                solve.assert_not_called()
            self.assertEqual(json.loads((root/'trial/trial.json').read_text())['status'], 'error')

    def test_solver_receives_base_only_and_adaptive_loop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            factory = self.fixture(root)
            (factory/'gold/app.py').write_text('SECRET_GOLD = 42')
            def solve(config, repo, output, model):
                self.assertEqual(config['recovery']['strategy'], 'adaptive')
                self.assertNotIn('SECRET_GOLD', json.dumps(config))
                self.assertEqual((repo/'app.py').read_text(), 'VALUE = 1')
                (repo/'app.py').write_text('VALUE = 2')
                return {'status': 'passed', 'budget': {}, 'verification_attempts': [{}]}
            with patch('examples.run_factory_task.from_config', return_value=Mock()), \
                 patch('examples.run_factory_task.installed_versions'), \
                 patch('examples.run_factory_task.probe', return_value={'stdout': 'baseline failure'}), \
                 patch('examples.run_factory_task.transition_passed', return_value=True), \
                 patch('examples.run_factory_task.run', side_effect=solve):
                result = execute(factory, root/'trial', {})
            self.assertTrue(result['passed'])
            self.assertEqual((factory/'base/app.py').read_text(), 'VALUE = 1')

    def test_disabled_arm_has_no_recovery_controller_or_verification_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            factory = self.fixture(root)
            def solve(config, repo, output, model):
                self.assertEqual(config['recovery'], {'max_actions': 0})
                self.assertEqual(config['verification_repair_attempts'], 0)
                return {'status': 'failed', 'budget': {}}
            with patch('examples.run_factory_task.from_config'), \
                 patch('examples.run_factory_task.installed_versions'), \
                 patch('examples.run_factory_task.probe', return_value={'stdout': 'failure'}), \
                 patch('examples.run_factory_task.transition_passed', return_value=True), \
                 patch('examples.run_factory_task.run', side_effect=solve):
                self.assertFalse(execute(factory, root/'trial', {}, repair_attempts=0)['passed'])
