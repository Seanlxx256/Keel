import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.core import Budget, BudgetExceeded, Ledger, Limits, PolicyDenied, Trace
from keel.gateway import ToolGateway
from keel.workspace import Workspace


class MemoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        meta = self.repo / '.keel'
        meta.mkdir()
        self.ledger = Ledger(meta / 'ledger.sqlite')
        self.addCleanup(self.ledger.close)
        self.ws = Workspace(self.repo, Budget(Limits()), self.ledger, Trace(meta / 'trace.jsonl'))
        (self.repo / 'app.py').write_text('VALUE = 1\n')

    def test_search_reuses_payload_across_roles_but_keeps_recall_private(self):
        scout, implementer = ToolGateway('scout', self.ws), ToolGateway('implementer', self.ws)
        first = scout.call('search_code', {'query': 'VALUE'})
        with patch.object(Path, 'read_text', side_effect=AssertionError('must not rescan text')):
            second = implementer.call('search_code', {'query': 'VALUE'})
        self.assertNotEqual(first['fact_id'], second['fact_id'])
        self.assertFalse(self.ledger.recall(first['fact_id'])['cache_hit'])
        self.assertTrue(self.ledger.recall(second['fact_id'])['cache_hit'])
        self.assertEqual(self.ws.budget.tool_calls, 2)
        with self.assertRaises(PolicyDenied):
            implementer.call('recall', {'fact_id': first['fact_id']})
        self.assertEqual(self.ledger.statistics()['cache_hits'], 1)

    def test_add_edit_delete_and_query_limit_invalidate_search(self):
        self.assertFalse(self.ws.search('VALUE')['cache_hit'])
        self.assertTrue(self.ws.search('VALUE')['cache_hit'])
        (self.repo / 'app.py').write_text('VALUE = 2\n')
        changed = self.ws.search('VALUE')
        self.assertFalse(changed['cache_hit'])
        self.assertEqual(changed['matches'][0]['text'], 'VALUE = 2')
        (self.repo / 'new.py').write_text('VALUE = 3\n')
        self.assertEqual(len(self.ws.search('VALUE')['matches']), 2)
        (self.repo / 'app.py').unlink()
        self.assertEqual(self.ws.search('VALUE')['matches'][0]['file'], 'new.py')
        self.assertFalse(self.ws.search('VALUE', limit=1)['cache_hit'])

    def test_list_cache_persists_and_hits_still_obey_budget(self):
        self.ws.list_files()
        self.assertTrue(self.ws.list_files()['cache_hit'])
        other = Ledger(self.repo / '.keel' / 'ledger.sqlite')
        self.addCleanup(other.close)
        ws = Workspace(self.repo, Budget(Limits(max_tool_calls=1)), other, self.ws.trace)
        self.assertTrue(ws.list_files()['cache_hit'])
        with self.assertRaises(BudgetExceeded):
            ws.list_files()
        (self.repo / 'new.py').write_text('pass\n')
        self.assertFalse(self.ws.list_files()['cache_hit'])

    def test_repository_change_during_scan_does_not_publish_cache(self):
        original = Path.read_text
        def read(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path.name == 'app.py':
                path.write_text('VALUE = 2\n')
            return result
        with patch.object(Path, 'read_text', read):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                self.ws.search('VALUE')
        self.assertEqual(self.ledger.statistics()['cache_entries'], 0)
        self.assertEqual(self.ws.search('VALUE')['matches'][0]['text'], 'VALUE = 2')

    def test_host_handoff_grants_selected_copies_without_sharing_history(self):
        scout, planner = ToolGateway('scout', self.ws), ToolGateway('planner', self.ws)
        first = scout.call('read_file', {'path': 'app.py'})
        with self.assertRaises(PolicyDenied):
            planner.accept_evidence(scout, [first['fact_id'], 999999])
        self.assertFalse(planner.visible_facts)
        refs = planner.accept_evidence(scout, [first['fact_id']])
        self.assertNotEqual(refs[0]['fact_id'], first['fact_id'])
        self.assertIn('VALUE', planner.call('recall', {'fact_id': refs[0]['fact_id']})['text'])
        with self.assertRaises(PolicyDenied):
            planner.call('recall', {'fact_id': first['fact_id']})
        self.assertNotIn('accept_evidence', planner.catalog())
