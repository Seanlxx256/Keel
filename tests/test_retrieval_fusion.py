import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from examples.replay_retrieval_fusion import fuse_order, replay


class RetrievalFusionTests(unittest.TestCase):
    def test_agreement_and_empty_preserve_baseline(self):
        self.assertEqual(fuse_order([]), [])
        self.assertEqual(fuse_order([0, 1, 2, 3]), [0, 1, 2, 3])

    def test_equal_opposite_ranks_break_ties_by_baseline(self):
        self.assertEqual(fuse_order([1, 0]), [0, 1])
        self.assertEqual(fuse_order([3, 2, 1, 0]), [0, 3, 1, 2])

    def test_invalid_permutations_rejected(self):
        for order in ([0, 0], [1], [-1], [True], [.0]):
            with self.subTest(order=order), self.assertRaises(ValueError):
                fuse_order(order)

    def test_changed_source_receipt_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source.json'
            source.write_text('{"instances": []}')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            evaluation = root/'evaluation.json'
            evaluation.write_text(json.dumps({'status': 'completed', 'line_budget': 100,
                'symbol_line_cap': 32, 'inputs_sha256': {str(source): digest}}))
            source.write_text('{"instances": [], "changed": true}')
            with self.assertRaisesRegex(ValueError, 'input changed'):
                replay(source, [], evaluation, root/'output')
            self.assertFalse((root/'output').exists())


if __name__ == '__main__':
    unittest.main()
