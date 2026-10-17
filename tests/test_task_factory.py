import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from keel.core import Budget, Limits, BudgetExceeded
from keel.task_factory import EnvironmentPlanner, construct, freeze_test_workspaces, transition_passed, validate_recipe, recipe_fingerprint
from keel.models import Reply
from examples.run_autonomous_campaign import discover, solver_config


class FactoryTests(unittest.TestCase):
    def recipe(self):
        return {'python': '3.11', 'common': ['pytest==7.4.4'], 'old': 'dependency==1.0', 'new': 'dependency==2.0'}

    def cell(self, passing):
        return {'backend': 'docker', 'returncode': 0 if passing else 1, 'timeout': False,
                'metadata': {'collected': 2, 'skipped': 0, 'failures': 0 if passing else 1,
                             'errors': 0, 'test_ids': {'test::one': 1, 'test::two': 1}}}

    def test_recipe_rejects_shell_urls_duplicate_targets_and_unpinned_packages(self):
        for changes in ({'new': 'dependency==2; echo bad'}, {'new': 'https://bad/package'},
                        {'common': ['pytest>=7']}, {'common': ['pytest==7', 'dependency==1']},
                        {'new': 'other==2'}, {'python': '3.11\nRUN command'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_recipe({**self.recipe(), **changes})

    def test_schema_confusion_and_bad_pins_receive_specific_feedback_then_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, gold = self.snapshots(root)
            invalid = {**self.recipe(), 'common': ['pytest']}
            schema_confusion = {'type': 'object', 'properties': self.recipe()}
            responses = [invalid, schema_confusion, self.recipe()]
            messages = []
            class Model:
                def complete_json(self, request, **kwargs):
                    messages.append(request)
                    return Reply(json.dumps(responses[len(messages)-1]), 10)
            budget = Budget(Limits(max_wallclock=100, max_tokens=100000, max_model_calls=3))
            planner = EnvironmentPlanner(Model(), root, budget)
            with patch('keel.task_factory.build_environment', return_value=('sha256:'+'a'*64, {'returncode': 0})) as build, \
                 patch('keel.task_factory.installed_versions', return_value={}), \
                 patch('keel.task_factory.probe', side_effect=[self.cell(True), self.cell(False), self.cell(True)]):
                result, _ = construct({'title': 'Dependency compatibility'}, base, gold, root/'factory', planner)
            self.assertEqual(result['status'], 'transition_verified')
            self.assertEqual(budget.model_calls, 3)
            self.assertEqual(build.call_count, 2)
            feedback = json.loads(messages[1][1]['content'])['observation']
            self.assertIn("'pytest'", feedback['error'])
            self.assertEqual(json.loads(feedback['previous_response']), invalid)
            self.assertIn('INSTANCE', json.loads(messages[2][1]['content'])['observation']['error'])

    def test_runtime_transition_is_not_invented_as_a_package_upgrade(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, gold = self.snapshots(root)
            planner = Mock()
            planner.budget = Budget(Limits())
            planner.plan.return_value = self.recipe()
            with patch('keel.task_factory.build_environment') as build:
                result, _ = construct({'title': 'Python 3.12 compatibility'}, base, gold, root/'factory', planner)
            self.assertEqual(result['status'], 'environment_unresolved')
            self.assertTrue(all('do not invent' in row['error'] for row in result['attempts']))
            build.assert_not_called()

    def test_protocol_corrections_leave_build_recovery_available(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, gold = self.snapshots(root)
            responses = [{**self.recipe(), 'common': ['pytest']}, {'type': 'object'},
                         self.recipe(), {**self.recipe(), 'python': '3.10'}]
            requests = []
            class Model:
                def complete_json(self, messages, **kwargs):
                    requests.append(messages)
                    return Reply(json.dumps(responses[len(requests)-1]), 10)
            budget = Budget(Limits(max_tokens=100000, max_model_calls=4))
            planner = EnvironmentPlanner(Model(), root, budget)
            with patch('keel.task_factory.build_environment', side_effect=[
                    (None, {'returncode': 1, 'tail': 'Observed packaging runtime failure'}),
                    ('sha256:'+'a'*64, {}), ('sha256:'+'b'*64, {})]), \
                 patch('keel.task_factory.installed_versions', return_value={}), \
                 patch('keel.task_factory.probe', side_effect=[self.cell(True), self.cell(False), self.cell(True)]):
                result, _ = construct({'title': 'Compatibility'}, base, gold, root/'factory', planner, attempts=2)
            self.assertEqual(result['status'], 'transition_verified')
            self.assertEqual(len(result['attempts']), 2)
            self.assertEqual(budget.model_calls, 4)
            self.assertIn('Observed packaging runtime failure', requests[3][1]['content'])

    def test_protocol_correction_cannot_bypass_global_model_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Mock()
            model.complete_json.return_value = Reply('{"type":"object"}', 1)
            budget = Budget(Limits(max_model_calls=1, max_tokens=100000))
            planner = EnvironmentPlanner(model, Path(temp), budget)
            with self.assertRaises(BudgetExceeded):
                planner.plan({}, None)
            self.assertEqual(model.complete_json.call_count, 1)

    def test_failed_recipe_reordered_by_model_is_corrected_before_another_build(self):
        with tempfile.TemporaryDirectory() as temp:
            old = self.recipe()
            old['common'] = ['pytest==7.4.4', 'pip==22.3.1']
            corrected = {**old, 'common': ['pytest==7.4.4', 'pip==24.0']}
            responses = [{**old, 'common': list(reversed(old['common']))}, corrected]
            requests = []
            class Model:
                def complete_json(self, messages, **kwargs):
                    requests.append(messages)
                    return Reply(json.dumps(responses[len(requests)-1]), 10)
            planner = EnvironmentPlanner(Model(), Path(temp), Budget(Limits(max_tokens=100000)))
            result = planner.plan({}, {'previous_recipe': old, 'builds': {'new': {'tail': 'pip check crashed'}}})
            self.assertEqual(result['common'], corrected['common'])
            self.assertIn('exact recipe already failed', requests[1][1]['content'])
            self.assertIn('pip check crashed', requests[1][1]['content'])
            self.assertEqual(recipe_fingerprint(old), recipe_fingerprint(responses[0]))

    def test_resolved_python_inventory_is_frozen_before_acceptance_and_reused_by_solver(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, gold = self.snapshots(root)
            recipe = {'kind': 'python', 'python': '3.12', 'old': '3.11', 'new': '3.12',
                      'common': ['pytest==7.4.4', 'pip==24.0', 'setuptools==68.2.2', 'wheel==0.41.3'],
                      'resolve_dependencies': True}
            pins = dict(pin.split('==') for pin in recipe['common'])
            pins['indirect'] = '1.0'
            planner = Mock()
            planner.budget = Budget(Limits())
            planner.plan.return_value = recipe
            with patch('keel.task_factory.build_environment', return_value=('sha256:'+'a'*64, {})), \
                 patch('keel.task_factory.installed_versions', return_value={'inventory': pins}), \
                 patch('keel.task_factory.probe', side_effect=[self.cell(True), self.cell(False), self.cell(True)]):
                result, _ = construct({'title': 'Python 3.12 compatibility'}, base, gold, root/'factory', planner)
            self.assertEqual(result['status'], 'transition_verified')
            self.assertIn('indirect==1.0', result['recipe']['common'])
            self.assertNotIn('resolve_dependencies', result['recipe'])
            self.assertTrue((root/'factory/attempt-1/resolved-recipe.json').exists())

    def test_target_distribution_cannot_be_duplicated_in_common(self):
        with self.assertRaisesRegex(ValueError, 'only in old/new'):
            validate_recipe({**self.recipe(), 'common': ['pytest==7.4.4', 'dependency==1.0']})

    def test_gate_requires_real_fail_to_pass_and_identical_nonempty_test_ids(self):
        cells = {'base_old': self.cell(True), 'base_new': self.cell(False), 'gold_new': self.cell(True)}
        self.assertTrue(transition_passed(cells))
        for cell, field, value in [('base_new', 'returncode', 0), ('gold_new', 'timeout', True)]:
            changed = json.loads(json.dumps(cells))
            changed[cell][field] = value
            self.assertFalse(transition_passed(changed))
        for field, value in [('skipped', 1), ('collected', 0), ('test_ids', {'different': 2})]:
            changed = json.loads(json.dumps(cells))
            changed['gold_new']['metadata'][field] = value
            self.assertFalse(transition_passed(changed))

    def snapshots(self, directory):
        for side in ('base', 'gold'):
            root = directory/side
            (root/'tests').mkdir(parents=True)
            (root/'lib.py').write_text('VALUE = ' + ('1' if side == 'base' else '2'))
            (root/'tests/test_lib.py').write_text('assert ' + ('False' if side == 'base' else 'True'))
        return directory/'base', directory/'gold'

    def test_freezes_upstream_tests_without_copying_gold_library_to_base(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, gold = self.snapshots(root)
            (base/'tests/test_removed.py').write_text('assert False')
            output = root/'work'
            output.mkdir()
            workspaces, frozen, tests = freeze_test_workspaces(base, gold, output)
            self.assertEqual((workspaces['base']/'lib.py').read_text(), 'VALUE = 1')
            self.assertEqual((workspaces['base']/'tests/test_lib.py').read_bytes(), (gold/'tests/test_lib.py').read_bytes())
            self.assertTrue((workspaces['base']/'tests/test_removed.py').exists())
            self.assertEqual((workspaces['base']/'tests/test_removed.py').read_bytes(),
                             (workspaces['gold']/'tests/test_removed.py').read_bytes())
            self.assertEqual(tests, ['tests'])
            self.assertIn('tests/test_lib.py', frozen)

    def test_removed_upstream_tests_require_review_before_any_model_or_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, gold = self.snapshots(root)
            (base/'tests/obsolete_test.py').write_text('import removed_module')
            planner = Mock()
            with patch('keel.task_factory.build_environment') as build:
                result, workspaces = construct({'title': 'Compatibility'}, base, gold, root/'factory', planner)
            self.assertEqual(result['status'], 'acceptance_review_required')
            self.assertEqual(result['acceptance_preflight']['removed_upstream_tests'], ['tests/obsolete_test.py'])
            self.assertEqual(workspaces, {})
            planner.plan.assert_not_called()
            build.assert_not_called()
            self.assertTrue((base/'tests/obsolete_test.py').exists())

    def test_build_failure_is_observed_and_replanned_while_acceptance_stays_frozen(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, gold = self.snapshots(root)
            planner = Mock()
            planner.budget = Budget(Limits(max_wallclock=100, max_tokens=100000, max_model_calls=10))
            recipe = self.recipe()
            planner.plan.side_effect = [recipe, {**recipe, 'python': '3.10'}]
            calls = []
            def build(recipe, phase, directory, timeout):
                calls.append(phase)
                if len(calls) == 1:
                    return None, {'returncode': 1, 'tail': 'missing dependency'}
                return 'sha256:'+'a'*64, {'returncode': 0}
            with patch('keel.task_factory.build_environment', side_effect=build), \
                 patch('keel.task_factory.installed_versions', return_value={}), \
                 patch('keel.task_factory.probe', side_effect=[self.cell(True), self.cell(False), self.cell(True)]):
                result, _ = construct({'title': 'Compatibility'}, base, gold, root/'factory', planner)
            self.assertEqual(result['status'], 'transition_verified')
            self.assertIn('missing dependency', str(planner.plan.call_args_list[1]))
            self.assertEqual(len(result['attempts']), 2)
            self.assertFalse(result['benchmark_ready'])

    def test_same_environment_plan_stops_instead_of_rebuilding_forever(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, gold = self.snapshots(root)
            planner = Mock()
            planner.budget = Budget(Limits())
            planner.plan.return_value = self.recipe()
            with patch('keel.task_factory.build_environment', return_value=(None, {'returncode': 1})) as build:
                result, _ = construct({'title': 'Compatibility'}, base, gold, root/'factory', planner)
            self.assertEqual(build.call_count, 1)
            self.assertEqual(result['attempts'][-1]['status'], 'stopped')

    def test_pytest_stdout_failure_reaches_environment_replanning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, gold = self.snapshots(root)
            planner = Mock()
            planner.budget = Budget(Limits(max_wallclock=100, max_tokens=100000, max_model_calls=10))
            planner.plan.side_effect = [self.recipe(), {**self.recipe(), 'python': '3.10'}]
            failed = {**self.cell(False), 'stdout': 'ImportError: missing_fixture_dependency', 'stderr': ''}
            with patch('keel.task_factory.build_environment', return_value=('sha256:'+'a'*64, {'returncode': 0})), \
                 patch('keel.task_factory.installed_versions', return_value={}), \
                 patch('keel.task_factory.probe', side_effect=[failed, failed, failed,
                       self.cell(True), self.cell(False), self.cell(True)]):
                result, _ = construct({'title': 'Compatibility'}, base, gold, root/'factory', planner)
            observation = planner.plan.call_args_list[1].args[1]
            self.assertIn('missing_fixture_dependency', observation['tests']['base_old']['stdout_tail'])
            self.assertEqual(result['status'], 'transition_verified')

    def test_repository_discovery_rejects_partial_results(self):
        with self.assertRaises(ValueError):
            discover(lambda route: {'incomplete_results': True, 'items': []}, 2)
        self.assertEqual(discover(lambda route: {'incomplete_results': False, 'items': [{'full_name': 'org/repo'}]}, 2), ['org/repo'])
        self.assertEqual(discover(lambda route: {'incomplete_results': False, 'items':
            [{'full_name': 'org/known'}, {'full_name': 'org/new'}]}, 1, excluded={'org/known'}), ['org/new'])

    def test_solver_config_excludes_gold_and_curator_source_paths(self):
        factory = {'candidate': {'title': 'Compatibility', 'gold_commit': 'secret-gold', 'files': ['secret/path.py']},
                   'recipe': self.recipe(), 'images': {'new': 'sha256:'+'a'*64},
                   'attempts': [{'cells': {'base_new': {'stdout': 'observed error'}}}]}
        config = solver_config({'name': 'fake'}, factory, ['tests'], Budget(Limits()), 24000)
        text = json.dumps(config)
        self.assertNotIn('secret-gold', text)
        self.assertNotIn('secret/path.py', text)
        self.assertEqual(config['recovery']['max_actions'], 6)
        self.assertIn('{junit}', text)
