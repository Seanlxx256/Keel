import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.reranker_worker import stable_order, run


class RerankerTests(unittest.TestCase):
    def test_finite_scores_stable_ties_complete_permutation(self):
        self.assertEqual(stable_order([.5, .8, .8, -.3], 4), [1, 2, 0, 3])
        for values, count in [([float('nan')], 1), ([float('inf')], 1), ([.5], 2)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                stable_order(values, count)

    def test_worker_scores_only_supplied_pairs_with_real_order_contract(self):
        # Model stub validates the orchestration contract, not neural quality.
        class Torch:
            @staticmethod
            def manual_seed(seed):
                pass
            @staticmethod
            def set_num_threads(count):
                pass
        class Model:
            def __init__(self, name, **kwargs):
                self.kwargs = kwargs
            def predict(self, pairs, **kwargs):
                self_test.assertEqual(pairs, [('query', 'a.py\nfirst'), ('query', 'b.py\nsecond')])
                return [-2, 3]
        self_test = self
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root/'request.json'
            request.write_text(json.dumps({'model': 'test-only', 'cache': str(root/'cache'),
                'jobs': [dict(id='job', query='query', documents=[dict(text='a.py\nfirst'), dict(text='b.py\nsecond')])]}))
            from types import SimpleNamespace
            with patch.dict('sys.modules', {'torch': Torch, 'sentence_transformers': SimpleNamespace(CrossEncoder=Model)}), \
                    patch('examples.reranker_worker.metadata.version', return_value='test-only'):
                measured = run(request, root/'output.json')
            self.assertEqual(measured['status'], 'completed')
            self.assertEqual(measured['jobs'][0]['order'], [1, 0])
            self.assertEqual(measured['pair_count'], 2)
            self.assertEqual(measured['generation_model_calls'], 0)


if __name__ == '__main__':
    unittest.main()
