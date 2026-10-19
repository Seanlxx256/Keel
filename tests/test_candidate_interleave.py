import unittest
from examples.replay_candidate_interleave import interleave


def region(name, start=1, end=5):
    return dict(path=name, start_line=start, end_line=end)


class CandidateInterleaveTests(unittest.TestCase):
    def test_alternation_native_order_dedup_and_input_immutability(self):
        first = [region('a'), region('b'), region('c')]
        second = [region('a'), region('d')]
        result = interleave(first, second)
        self.assertEqual([r['path'] for r in result], ['a','b','d','c'])
        result[0]['path'] = 'changed'
        self.assertEqual(first[0]['path'], 'a')

    def test_budget_empty_sources_and_unequal_overlaps(self):
        self.assertEqual(interleave([], []), [])
        self.assertEqual(len(interleave([region(str(i)) for i in range(150)], [])), 100)
        self.assertEqual(interleave([], [region('a')]), [region('a')])
        self.assertEqual(len(interleave([region('a')], [region('a',2,6)])), 2)


if __name__ == '__main__':
    unittest.main()
