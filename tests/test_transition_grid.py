import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from examples import run_transition_grid as grid
from examples import run_transition_task as runner


class GridTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root/'.keel/independent-snapshots/encode--httpx'/('a'*40)
        source.mkdir(parents=True)
        (source/'a.py').write_bytes(b'value = 1\n')
        self.package = self.root/'package'
        self.package.mkdir()
        (self.package/'manifest.json').write_text('{}')
        (self.package/'acceptance.py').write_text('pass')
        self.model = self.root/'model.json'
        self.model.write_text(json.dumps({'provider': 'ollama', 'name': 'fixture'}))
        self.manifest = {'curator_receipt': {'base_inventory': runner.inventory(source)},
            'acceptance': {'image': 'sha256:'+'a'*64, 'versions': {'httpcore': '0.13.0'}}}
        self.task = {'id': 'httpx-1588', 'base_commit': 'a'*40, 'goal': 'Repair compatibility'}

    def prepare(self, output):
        with patch.object(runner, 'load_package', return_value=(self.manifest, self.task)):
            return grid.prepare_grid(self.root, self.package, self.model, output, [12000, 24000, 48000])

    def test_only_cap_differs_and_order_is_seeded_without_provider_calls(self):
        first, second = self.root/'one', self.root/'two'
        with patch.object(runner, 'from_config') as factory:
            a, b = self.prepare(first), self.prepare(second)
            factory.return_value.complete_json.assert_not_called()
            factory.return_value.check_credentials.assert_not_called()
        self.assertEqual(a['runs'], b['runs'])
        self.assertEqual(a['unique_tasks'], 1)
        self.assertEqual(a['heldout_tasks'], 0)
        frozen = [json.loads((first/r['directory']/'prepared.json').read_text()) for r in a['runs']]
        self.assertTrue(all(grid.comparable(f) == grid.comparable(frozen[0]) for f in frozen))
        with self.assertRaises(ValueError):
            grid.prepare_grid(self.root, self.package, self.model, self.root/'bad', [12000, 12000])

    def test_every_outcome_retained_and_exclusive_grid_refuses_repeat(self):
        output = self.root/'grid'
        plan = self.prepare(output)
        outcomes = [RuntimeError('environment unavailable'),
            {'status': 'completed', 'passed': False, 'executed': True},
            {'status': 'completed', 'passed': True, 'executed': True}]
        with patch.object(grid, 'execute', side_effect=outcomes) as execute:
            result = grid.execute_grid(self.root, output)
            self.assertEqual(execute.call_count, 3)
        self.assertEqual(len(result['records']), len(plan['runs']))
        self.assertEqual([r['status'] for r in result['records']], ['runner_error', 'completed', 'completed'])
        self.assertFalse(result['all_passed'])
        with self.assertRaises(FileExistsError):
            grid.execute_grid(self.root, output)

    def test_changed_arm_blocks_entire_grid_before_first_execution(self):
        output = self.root/'grid'
        plan = self.prepare(output)
        (output/plan['runs'][-1]['directory']/'repo/a.py').write_bytes(b'value = 2\n')
        with patch.object(grid, 'execute') as execute, self.assertRaises(ValueError):
            grid.execute_grid(self.root, output)
        execute.assert_not_called()
        self.assertFalse((output/'grid-started.json').exists())
