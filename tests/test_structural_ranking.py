import unittest
from compass.retrieval import Routing
from compass.structural import rank_structure


class StructuralRankingTests(unittest.TestCase):
    def test_only_reorders_original_candidates_without_mutation(self):
        rows = [dict(id=str(i), score=1., code='same') for i in range(5)]
        ranked = rank_structure(rows, [('0','4'),('1','4'),('2','4'),('outside','4')])
        self.assertEqual({r['id'] for r in ranked}, {r['id'] for r in rows})
        self.assertLess([r['id'] for r in ranked].index('4'),4)
        self.assertNotIn('structural_evidence', rows[0])
        self.assertTrue(all(r['code']=='same' for r in ranked))

    def test_deterministic_duplicate_and_unresolved_edges(self):
        rows = [dict(id=str(i), score=.1) for i in range(4)]
        edges = [('0','3'),('1','3')]
        self.assertEqual(rank_structure(rows, edges),rank_structure(rows,edges[::-1]+edges+[(None,'3')]))
        self.assertEqual([r['id'] for r in rank_structure(rows,[])],[r['id'] for r in rows])
        self.assertEqual(Routing().ranking,'rrf')
        self.assertEqual(Routing(ranking='code-aware-structure').ranking,'code-aware-structure')

    def test_duplicate_candidates_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            rank_structure([dict(id='x'),dict(id='x')],[])


if __name__ == '__main__':
    unittest.main()
