from pathlib import Path
import tempfile
import unittest

from keel.experience import ExperienceStore
from keel.tool_recovery import symbol_queries


class ToolRecoveryTests(unittest.TestCase):
    def test_distinct_queries_reuse_verified_experience_and_keep_call_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ExperienceStore(Path(directory)/'experience.sqlite')
            for term in ['FirstSymbol', 'OtherSymbol']:
                calls = []
                def invoke(name, substring, timeout):
                    calls.append((name, substring))
                    if substring:
                        raise ValueError('Matched 864>max_matches=100 symbols.\nUntrusted tool text')
                    return [{'name': name}]
                result = symbol_queries(invoke, [term], version='test', store=store)
                self.assertEqual(calls, [(term, True), (term, False)])
                self.assertEqual(result['tool_calls'], 2)
                self.assertTrue(any(e['event'] == 'verified' for e in result['recovery']))
                retrieved = next(e['actions'] for e in result['recovery'] if e['event'] == 'retrieved')
                self.assertEqual(retrieved, [] if term == 'FirstSymbol' else ['exact_symbol_query_v1'])

    def test_unknown_failure_is_not_retried(self):
        calls = []
        def invoke(*args):
            calls.append(args)
            raise PermissionError('denied')
        with self.assertRaises(PermissionError):
            symbol_queries(invoke, ['Symbol'], version='test')
        self.assertEqual(len(calls), 1)

    def test_root_query_after_exact_overflow_records_failed_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ExperienceStore(Path(directory)/'experience.sqlite')
            calls = []
            def invoke(term, substring, timeout):
                calls.append((term, substring))
                if not term.startswith('/'):
                    raise ValueError('Matched 217>max_matches=100 symbols.')
                return [{'name': term}]
            result = symbol_queries(invoke, ['Symbol'], version='test', store=store)
            self.assertEqual(calls, [('Symbol', True), ('Symbol', False), ('/Symbol', False)])
            with store.connect() as db:
                outcomes = db.execute('SELECT action,outcome FROM attempts').fetchall()
            self.assertIn(('exact_symbol_query_v1', 'failed'), outcomes)
            self.assertIn(('root_symbol_query_v1', 'verified'), outcomes)
            self.assertNotIn(('exact_symbol_query_v1', 'verified'), outcomes)

    def test_recovery_does_not_expand_eight_call_budget(self):
        calls = []
        def invoke(term, substring, timeout):
            calls.append((term, substring))
            if term == 'Symbol0' and substring:
                raise ValueError('Matched 500>max_matches=100 symbols.')
            return []
        result = symbol_queries(invoke, ['Symbol'+str(i) for i in range(8)], version='test')
        self.assertEqual(len(calls), 8)
        self.assertEqual(result['unqueried_terms'], ['Symbol7'])
