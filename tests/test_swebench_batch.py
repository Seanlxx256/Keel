import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.run_swebench_batch import select, prepare, execute, verify_plan


class SwebenchBatchTests(unittest.TestCase):
    def test_configurable_five_repository_selection(self):
        rows = [{'instance_id': f'r{i}__lib-1', 'repo': f'r{i}/lib'} for i in range(6)]
        chosen = select(rows, set(), set(), count=5, repositories=5)
        self.assertEqual(len(chosen), 5)
        self.assertEqual(len({row['repo'] for row in chosen}), 5)

    def rows(self):
        return [{'instance_id': f'{repo}__lib-{number}', 'repo': f'{repo}/lib',
                 'base_commit': 'a'*40, 'problem_statement': 'Issue', 'patch': 'gold', 'test_patch': 'tests'}
                for repo in ('alpha', 'beta', 'gamma') for number in range(1, 4)]

    def fixture(self, root):
        (root/'examples').mkdir()
        (root/'examples/evaluation_development_registry.json').write_text('{"tasks":[]}')
        source = root/'data.json'
        source.write_text(json.dumps(self.rows()))
        model = root/'model.json'
        model.write_text('{"name":"test"}')
        with patch('examples.run_swebench_batch.seen_tasks', return_value=(set(), {}, [])):
            return prepare(root, source, model, root/'python', root/'batch')

    def test_seeded_selection_excludes_seen_tasks_and_is_order_independent(self):
        rows = self.rows()
        excluded = {'alpha__lib-1'}
        chosen = select(rows, excluded, {'gamma/lib'})
        self.assertEqual(chosen, select(list(reversed(rows)), excluded, {'gamma/lib'}))
        self.assertEqual(len(chosen), 3)
        self.assertEqual(len({row['repo'] for row in chosen}), 2)
        self.assertNotIn('alpha__lib-1', [row['instance_id'] for row in chosen])

    def test_settings_drift_rejected_before_any_harness_or_model_call(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root/'model.json').write_text('{"name":"changed"}')
            with patch('examples.run_swebench_batch.grade') as grade:
                with self.assertRaisesRegex(ValueError, 'settings changed'):
                    execute(root, root/'batch')
                grade.assert_not_called()

    def test_failed_reference_remains_in_fixed_list_and_later_tasks_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.fixture(root)
            calls = []
            def reference(*args, **kwargs):
                calls.append(args)
                return {'status': 'graded', 'official_resolved': len(calls) != 1}
            with patch('examples.run_swebench_batch.grade', side_effect=reference), \
                 patch('examples.run_swebench_batch.run_task', return_value={'status': 'completed',
                       'runtime_status': 'failed', 'official_resolved': False}) as run:
                result = execute(root, root/'batch')
            self.assertEqual(len(result['records']), 3)
            self.assertEqual(result['records'][0]['instance_id'], plan['tasks'][0]['instance_id'])
            self.assertEqual(result['counts']['reference_failed_or_error'], 1)
            self.assertEqual(result['counts']['agent_executed'], 2)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(result['counts']['resolved'], 0)
            self.assertEqual(len({row['instance_id'] for row in result['records']}), 3)
            with self.assertRaises(FileExistsError):
                execute(root, root/'batch')

    def test_changed_reference_cannot_enter_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.fixture(root)
            reference = root/'batch'/plan['tasks'][0]['directory']/'reference/predictions.jsonl'
            reference.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'reference changed'):
                verify_plan(root, root/'batch')
