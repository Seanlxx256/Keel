import tempfile
from pathlib import Path
import unittest

from examples.compare_retrieval_alternatives import paired_summary, rank_external, score
from examples.serena_retrieval_worker import query_identifiers


class RetrievalAlternativesTests(unittest.TestCase):
    def test_real_sqlite_search(self):
        documents = [dict(embed_text='', code=code) for code in ('banana pear', 'socket timeout')]
        rows, version = rank_external('sqlite_fts5', documents, 'socket')
        self.assertEqual(rows, [documents[1]])
        self.assertTrue(version)
        self.assertEqual(rank_external('sqlite_fts5', documents, '')[0], [])

    def test_missing_results_do_not_enter_paired_mean(self):
        records = [dict(instance=i, engine=engine, status='ok', metrics=dict(
            line_recall=value, line_precision=value, hit_file_rate=value))
            for i, engine, value in [('a', 'compass_cached_code-aware', .2),
                                     ('b', 'compass_cached_code-aware', .8), ('a', 'external', .4)]]
        records.append(dict(instance='b', engine='external', status='unavailable'))
        result = paired_summary(records)[0]
        self.assertEqual(result['paired_tasks'], 1)
        self.assertEqual(result['line_recall'], dict(external=.4, **{'compass_cached_code-aware': .2}))

    def test_ranges_checked_before_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'a.py').write_text('x = 1\n')
            with self.assertRaises(ValueError):
                score([dict(path='a.py', start_line=1, end_line=2)], {'repo': directory})

    def test_identifier_adapter_is_bounded_and_deduplicated(self):
        terms = query_identifiers('obj.send Blueprint Blueprint snake_name ' + ' '.join('Symbol'+str(i) for i in range(20)))
        self.assertEqual(terms[:3], ['send', 'Blueprint', 'snake_name'])
        self.assertEqual(len(terms), 8)


if __name__ == '__main__':
    unittest.main()
