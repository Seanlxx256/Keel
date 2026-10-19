import tempfile
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

from examples.compare_retrieval_alternatives import paired_summary, rank_external, score, run
from examples.serena_retrieval_worker import query_identifiers


class RetrievalAlternativesTests(unittest.TestCase):
    def test_completed_external_result_is_reused_without_tool_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root/'repo'
            repo.mkdir()
            (repo/'a.py').write_text('x\n')
            instance = dict(id='task', repo=str(repo), query='query', core_regions=[dict(path='a.py', start=1, end=1)],
                            optional_regions=[], core_files=['a.py'])
            directory = root/'instance'
            directory.mkdir()
            (directory/'sweep').mkdir()
            dataset = directory/'instance.jsonl'
            dataset.write_text('{}')
            (directory/'sweep/runs.jsonl').write_text('')
            source = root/'source.json'
            source.write_text(json.dumps({'instances': [dict(instance_id='task', snapshot=str(repo),
                measurements=[dict(ranking='code-aware', sweep=str(directory/'sweep/sweep.json'))])]}))
            candidate = dict(path='a.py', start_line=1, end_line=1)
            worker = Path(__file__).parents[1]/'examples/cocoindex_retrieval_worker.py'
            previous = root/'previous.json'
            previous.write_text(json.dumps({'line_budget': 100, 'symbol_line_cap': 32,
                'implementation_sha256': {worker.name: hashlib.sha256(worker.read_bytes()).hexdigest()},
                'records': [dict(instance='task', engine='cocoindex_semantic', status='ok',
                    index_ref='same', query_sha256=hashlib.sha256(b'query').hexdigest(),
                    dataset_sha256=hashlib.sha256(dataset.read_bytes()).hexdigest(),
                    embedding_settings={'model': 'Snowflake/snowflake-arctic-embed-xs'},
                    **score([candidate], instance))]}))
            index = MagicMock()
            index.metadata = {'index_ref': 'same'}
            index.db.execute.return_value = []
            manager = MagicMock()
            manager.__enter__.return_value = index
            with patch('examples.compare_retrieval_alternatives.load_swe_instance', return_value=instance), \
                    patch('examples.compare_retrieval_alternatives.RepositoryIndex', return_value=manager), \
                    patch('examples.compare_retrieval_alternatives.subprocess.run') as tool:
                measured = run(source, root/'output', engines=('cocoindex_semantic',), resume_report=previous)
            tool.assert_not_called()
            self.assertTrue(measured['records'][0]['reused'])
            self.assertEqual(measured['records'][0]['metrics']['line_recall'], 1)

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
