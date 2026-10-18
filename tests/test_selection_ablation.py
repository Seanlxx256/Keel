import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compass.selection_ablation import replay


class SelectionAblationTests(unittest.TestCase):
    def fixture(self, root, mismatch=False):
        folder = root/'instance/sweep'
        folder.mkdir(parents=True)
        (folder.parent/'instance.jsonl').write_text('{}')
        (folder/'sweep.json').write_text(json.dumps({'instance_id': 'repo-1', 'base_commit': 'base'}))
        a = {'rank': 1, 'id': 'a', 'path': 'a.py', 'start': 1, 'end': 1}
        b = {'rank': 2, 'id': 'b', 'path': 'b.py', 'start': 1, 'end': 1}
        runs = [{'mode': mode, 'repeat': 0, 'line_budget': 2, 'status': 'passed',
                 'result': {'index_ref': 'different' if mismatch and mode == 't2' else 'same',
                            'candidates': [a, b] if mode == 't1' else [a],
                            'usage': {'model_calls': 0 if mode == 't1' else 2}}} for mode in ('t1', 't2')]
        (folder/'runs.jsonl').write_text('\n'.join(json.dumps(r) for r in runs))
        source = root/'result.json'
        source.write_text(json.dumps({'instances': [{'instance_id': 'repo-1', 'snapshot': str(root),
            'measurements': [{'ranking': 'rrf', 'sweep': str(folder/'sweep.json')}]}]}))
        gold = {'id': 'repo-1', 'base_commit': 'base', 'core_regions': [{'path': 'b.py', 'start': 1, 'end': 1}],
                'optional_regions': [], 'core_files': ['b.py']}
        return source, gold

    def test_fixed_budget_replay_preserves_costs_and_labels_only_score_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, gold = self.fixture(root)
            with patch('compass.selection_ablation.load_swe_instance', return_value=gold):
                report = replay(source, root/'output', line_budget=2, symbol_line_cap=1, reserves=(1, 2))
            rows = {r['policy']: r for r in report['records']}
            self.assertEqual(rows['t2']['metrics']['line_recall'], 0)
            self.assertEqual(rows['t2_reserve_2']['metrics']['line_recall'], 1)
            self.assertTrue(all(r['metrics']['predicted_unique_lines'] <= 2 for r in rows.values()))
            self.assertEqual(rows['t2_reserve_2']['source_usage']['model_calls'], 2)
            self.assertEqual(report['new_model_calls'], 0)
            self.assertEqual(len(report['inputs_sha256']), 4)

    def test_mismatched_index_is_rejected_before_writing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, gold = self.fixture(root, mismatch=True)
            with patch('compass.selection_ablation.load_swe_instance', return_value=gold):
                with self.assertRaisesRegex(ValueError, 'indices differ'):
                    replay(source, root/'output')
            self.assertFalse((root/'output').exists())
