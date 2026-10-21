from contextlib import closing
from pathlib import Path
import tempfile
import unittest

from examples.evaluate_search_guidance import CASES, score
from keel.core import Budget, Limits, Ledger, Trace
from keel.workspace import Workspace


class SearchGuidanceEvaluationTests(unittest.TestCase):
    def evaluate(self, source, response, expected):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'module.py').write_bytes(source.encode())
            (root/'other.py').write_bytes(b'def load_profile(): pass\n')
            with closing(Ledger(root/'ledger.sqlite')) as ledger:
                workspace = Workspace(root, Budget(Limits(max_tool_calls=1)), ledger, Trace(root/'trace.jsonl'))
                return score(workspace, response, expected)

    def test_fixture_labels_have_real_scoped_matches_and_valid_absence(self):
        for case, source, _, expected in CASES:
            with self.subTest(case=case):
                response = {'query': expected or 'missing_handler', 'paths': ['module.py'],
                            'zero_hits_prove_absence': False}
                self.assertTrue(self.evaluate(source, response, expected)['passed'])

    def test_prose_miss_false_absence_and_wrong_scope_do_not_pass(self):
        source = 'def flush_queue(): pass\n'
        for query, paths, absence in [('flush_queue execution path', ['module.py'], False),
                                      ('flush_queue', ['module.py'], True),
                                      ('load_profile', ['other.py'], False)]:
            with self.subTest(query=query, paths=paths, absence=absence):
                self.assertFalse(self.evaluate(source, {'query': query, 'paths': paths,
                    'zero_hits_prove_absence': absence}, 'flush_queue')['passed'])
