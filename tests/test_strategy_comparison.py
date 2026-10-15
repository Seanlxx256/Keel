import json
from pathlib import Path
import tempfile
import unittest

from examples.compare_agent_strategies import compare
from examples.run_agent_baseline import controls, prepare


class StrategyComparisonTests(unittest.TestCase):
    def fixture(self, root):
        paths = [root/'proposal', root/'tool-loop']
        for directory, strategy in zip(paths, ('proposal', 'tool-loop')):
            manifest = prepare(directory, controls(), 'fixed-image', 'fixed-model', strategy=strategy)
            result = {'prepared_only': False, 'strategy': strategy, 'reproduction_sha256': 'fixed',
                'model_identity': {'name': 'fixed-model', 'digest': 'fixed'},
                'records': [{'id': t['id'], 'group': t['group'], 'status': 'completed',
                    'executed': True, 'passed': strategy == 'proposal', 'failure': None}
                    for t in manifest['tasks']]}
            (directory/'results.json').write_text(json.dumps(result), encoding='utf-8')
        return paths

    def test_failures_remain_paired_and_groups_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            result = compare(*self.fixture(Path(directory)))
            self.assertEqual(result['planned_pairs'], 2)
            self.assertFalse(result['pairs'][0]['strategies']['tool-loop']['passed'])
            self.assertEqual(result['pairs'][0]['group'], 'synthetic_control')

    def test_mismatched_inputs_and_missing_failures_are_rejected(self):
        for mutation in ('budget', 'missing', 'dependency', 'implementation', 'running'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                paths = self.fixture(Path(directory))
                filename = 'results.json' if mutation in ('missing', 'running') else 'manifest.json'
                path = paths[0]/filename
                value = json.loads(path.read_text(encoding='utf-8'))
                if mutation == 'budget':
                    value['tasks'][0]['config']['budget']['max_tokens'] += 1
                elif mutation == 'missing':
                    value['records'].pop()
                elif mutation == 'dependency':
                    value['tasks'][0]['config']['proposal']['dependencies'] = [{'distribution': 'anyio'}]
                elif mutation == 'implementation':
                    value['implementation_sha256']['keel/models.py'] = 'changed'
                else:
                    value['records'][0]['status'] = 'running'
                path.write_text(json.dumps(value), encoding='utf-8')
                with self.assertRaises(ValueError):
                    compare(*paths)
