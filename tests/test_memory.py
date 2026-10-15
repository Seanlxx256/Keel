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

    def test_context_selection_is_bounded_and_skips_stale_or_deleted_reads(self):
        from keel.context import handoff_context
        scout, planner = ToolGateway('scout', self.ws), ToolGateway('planner', self.ws)
        files = []
        for i in range(6):
            name = f'file{i}.py'
            (self.repo / name).write_text(f'VALUE = {i}\n')
            scout.call('read_file', {'path': name})
            files.append(name)
        refs = handoff_context(planner, [scout], files)
        self.assertEqual(len(refs), 4)
        self.assertEqual(len({ref['path'] for ref in refs}), 4)
        (self.repo / 'file5.py').write_text('VALUE = 99\n')
        (self.repo / 'file4.py').unlink()
        target = ToolGateway('implementer', self.ws)
        refs = handoff_context(target, [scout, planner], ['file5.py', 'file4.py'])
        self.assertEqual(refs, [])

    def test_disabled_cache_bypasses_existing_entries_and_preserves_budget(self):
        self.ws.read('app.py')
        self.ws.search('VALUE')
        entries = self.ledger.statistics()['cache_entries']
        ws = Workspace(self.repo, Budget(Limits()), self.ledger, self.ws.trace, memoization=False)
        for _ in range(2):
            self.assertFalse(ws.read('app.py')['cache_hit'])
            self.assertFalse(ws.search('VALUE')['cache_hit'])
        self.assertEqual(ws.tool_metrics['search_code'], {'requests': 2, 'cache_hits': 0, 'computations': 2})
        self.assertEqual(ws.budget.tool_calls, 4)
        self.assertEqual(self.ledger.statistics()['cache_entries'], entries)
        self.assertGreater(ws.snapshot_bytes, 0)

    def test_paired_benchmark_preserves_semantics_and_refuses_overwrite(self):
        from keel.memory_benchmark import run_benchmark
        result = run_benchmark(self.repo / 'experiment', files=2, lines=4, repeats=2, trials=2)
        self.assertTrue(result['all_passed'])
        self.assertEqual(result['summary']['off']['requests_per_trial'], result['summary']['on']['requests_per_trial'])
        self.assertLess(result['summary']['on']['computations_per_trial'], result['summary']['off']['computations_per_trial'])
        self.assertEqual(result['summary']['on']['snapshot_bytes_per_trial'], result['summary']['off']['snapshot_bytes_per_trial'])
        with self.assertRaises(FileExistsError):
            run_benchmark(self.repo / 'experiment')

    def test_runtime_cache_ablation_preserves_independent_acceptance(self):
        import sys
        from keel.runtime import run
        config = {'goal': 'Upgrade value', 'memoization': False,
                  'work_items': [{'id': 'change', 'edits': [{'path': 'app.py', 'old': 'VALUE = 1', 'new': 'VALUE = 2'}]}],
                  'acceptance': [[sys.executable, '-c', 'import app; assert app.VALUE == 2']]}
        result = run(config, self.repo, self.repo / '.keel' / 'runtime')
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(result['memory']['memoization'])
        self.assertEqual(result['memory']['cache_entries'], 0)
        self.assertEqual(result['memory']['tools']['read_file']['computations'], 1)
        with self.assertRaisesRegex(ValueError, 'memoization'):
            run({**config, 'memoization': 'false'}, self.repo, self.repo / '.keel' / 'invalid')
        self.assertFalse((self.repo / '.keel' / 'invalid').exists())
