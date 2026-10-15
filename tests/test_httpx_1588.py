import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from examples import reproduce_httpx_1588 as candidate


def matrix():
    rows = {}
    for phase, label, passing in [('base_old', 'old', True), ('base_new', 'new', False), ('gold_new', 'new', True)]:
        versions = dict(pin.split('==') for pin in candidate.COMMON)
        versions['httpcore'] = candidate.TARGETS[label]
        records = []
        for case in candidate.CASES:
            method = 'arequest' if case.startswith('async') else 'request'
            records.append({'case': case, 'passed': passing, 'type': 'AttributeError',
                'message': f"ConnectionPool has no attribute '{method}'"})
        rows[phase] = {'backend': 'docker', 'timeout': False, 'returncode': 0 if passing else 1,
            'stdout': json.dumps({'records': records, 'versions': versions})}
    return rows


class TransitionMatrixTests(unittest.TestCase):
    def test_all_three_cells_are_required_not_just_a_target_pass(self):
        self.assertTrue(candidate.assess(matrix()))
        for phase in matrix():
            runs = matrix()
            del runs[phase]
            self.assertFalse(candidate.assess(runs))

    def test_versions_case_identity_timeouts_and_unrelated_failure_are_rejected(self):
        for mutation in ('old_fails', 'new_passes', 'version', 'case', 'unrelated', 'timeout'):
            with self.subTest(mutation=mutation):
                runs = matrix()
                data = json.loads(runs['base_new']['stdout'])
                if mutation == 'old_fails':
                    runs['base_old']['returncode'] = 1
                elif mutation == 'new_passes':
                    data['records'][0]['passed'] = True
                elif mutation == 'version':
                    data['versions']['anyio'] = '4.0.0'
                elif mutation == 'case':
                    data['records'][0]['case'] = 'async_get'
                elif mutation == 'unrelated':
                    data['records'][0]['message'] = 'unrelated environment error'
                else:
                    runs['gold_new']['timeout'] = True
                runs['base_new']['stdout'] = json.dumps(data)
                self.assertFalse(candidate.assess(runs))

    def test_probe_is_local_functional_http_and_does_not_mock_the_pool_api(self):
        compile(candidate.PROBE, 'probe', 'exec')
        self.assertIn("HTTPServer(('127.0.0.1', 0)", candidate.PROBE)
        self.assertNotIn('unittest.mock', candidate.PROBE)
        self.assertNotIn('_pool', candidate.PROBE)
        self.assertIn('response.content ==', candidate.PROBE)

    def test_parent_and_exact_diff_inventory_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            base, gold = Path(directory)/'base', Path(directory)/'gold'
            files = ['httpx/_transports/default.py', 'setup.py', 'tests/test_exceptions.py']
            for root in (base, gold):
                for name in files:
                    path = root/name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('old' if root == base else 'new')
            row = {'base_commit': 'a'*40, 'gold_commit': 'b'*40}
            raw = SimpleNamespace(stdout='parent '+'a'*40+'\n\nmessage')
            with patch.object(candidate, 'check_snapshot'), patch.object(candidate.subprocess, 'run', return_value=raw):
                self.assertEqual(candidate.verify_sources(row, base, gold)['changed_files_curator_only'], files)
                (gold/'extra.py').write_text('unexpected')
                with self.assertRaises(ValueError):
                    candidate.verify_sources(row, base, gold)
                raw.stdout = 'parent '+'c'*40+'\n\nmessage'
                with self.assertRaisesRegex(ValueError, 'parent'):
                    candidate.verify_sources(row, base, gold)
