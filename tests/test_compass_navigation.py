import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compass.index import RepositoryIndex, build_index
from compass.service import CompassService
from compass.retrieval import Retriever, Routing
from keel.core import Budget, Ledger, Limits, PolicyDenied, Trace
from keel.gateway import ToolGateway
from keel.workspace import Workspace


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = 'class Store:\n    def save(self):\n        """Body documentation."""\n        return 42\n\ndef load():\n    return Store()\n'
        (self.root/'storage.py').write_text(self.source, encoding='utf-8')
        build_index(self.root, parser='python-ast')
        self.index = RepositoryIndex(self.root)
        self.addCleanup(self.index.close)

    def test_outline_pages_hierarchy_without_source_and_retains_identity(self):
        first = self.index.overview('storage.py', depth=1, limit=1)
        self.assertEqual(first['results'][0]['qualname'], 'Store')
        self.assertEqual(first['next_offset'], 1)
        rest = self.index.overview('storage.py', depth=1, offset=1)
        self.assertEqual([r['qualname'] for r in rest['results']], ['Store.save', 'load'])
        self.assertEqual([r['depth'] for r in rest['results']], [1, 0])
        self.assertIsNone(rest['next_offset'])
        self.assertNotIn('Body documentation', json.dumps(rest))
        self.assertNotIn('return 42', json.dumps(rest))
        self.assertEqual(first['index_ref'], self.index.metadata['index_ref'])
        self.assertEqual([r['qualname'] for r in self.index.overview('storage.py', depth=0)['results']], ['Store', 'load'])
        for kwargs in ({'offset': -1}, {'depth': True}, {'depth': 9}):
            with self.assertRaises(ValueError):
                self.index.overview('storage.py', **kwargs)
        offset, names = 0, []
        while offset is not None:
            page = self.index.overview('storage.py', depth=1, offset=offset, max_bytes=1400)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False).encode()), 1400)
            names.extend(r['qualname'] for r in page['results'])
            offset = page['next_offset']
        self.assertEqual(names, ['Store', 'Store.save', 'load'])

    def test_exact_line_location_chooses_inner_definition_without_model_or_hybrid(self):
        retriever = Retriever(self.index)
        with patch.object(retriever, 'hybrid', side_effect=AssertionError('T1 should not run')):
            for query in ('storage.py:4', 'storage.py:4:2', 'storage.py#L4'):
                result = retriever.retrieve(query)
                self.assertEqual(result['tier'], 'T0')
                self.assertEqual(result['results'][0]['qualname'], 'Store.save')
                self.assertEqual(result['usage']['model_calls'], 0)
        self.assertEqual(retriever.exact('storage.py:999', 10), [])
        self.assertEqual(retriever.exact('../storage.py:4', 10), [])

    def test_mcp_service_outline_and_stale_index_rejection(self):
        result = CompassService(self.root).call('get_symbols_overview', {'file': 'storage.py', 'limit': 1})
        self.assertTrue(result['truncated'])
        (self.root/'storage.py').write_text(self.source+'# changed\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale'):
            CompassService(self.root).call('get_symbols_overview', {'file': 'storage.py'})

    def test_native_keel_gateway_archives_outline_and_blocks_internal_metadata(self):
        output = self.root/'.keel/navigation'
        output.mkdir(parents=True)
        ledger = Ledger(output/'ledger.sqlite')
        self.addCleanup(ledger.close)
        workspace = Workspace(self.root, Budget(Limits()), ledger, Trace(output/'trace.jsonl'),
                              retrieval={'provider': 'compass'})
        gateway = ToolGateway('scout', workspace)
        result = gateway.call('get_symbols_overview', {'file': 'storage.py', 'depth': 1})
        self.assertIn(result['fact_id'], gateway.observed_facts)
        fact = ledger.recall(result['fact_id'])
        self.assertEqual([row['qualname'] for row in fact['results']], ['Store', 'Store.save', 'load'])
        self.assertNotIn('return 42', result['preview'])
        with self.assertRaises(PolicyDenied):
            gateway.call('get_symbols_overview', {'file': '.keel/private.py'})

    def test_opt_in_t2_reserves_seed_with_explicit_provenance_not_model_read_claim(self):
        rows = [dict(row) for row in self.index.db.execute('SELECT * FROM symbols ORDER BY start_line')]
        signals = {'vector_available': False}
        for reserve in (0, 1):
            retriever = Retriever(self.index, model=object(), routing=Routing(t2_preserve_top=reserve))
            with patch.object(retriever, 'hybrid', return_value=(rows, signals, [])), \
                 patch.object(retriever, 'explore', return_value=([], 'completed')):
                result = retriever.retrieve('unresolved behavior', limit=2, mode='t2')
            self.assertEqual(len(result['results']), reserve)
            if reserve:
                self.assertEqual(result['results'][0]['selection_source'], 't1_reserved')
                self.assertFalse(result['results'][0]['t2_selected'])
        for value in (True, -1, 101):
            with self.assertRaises(ValueError):
                Routing(t2_preserve_top=value)
