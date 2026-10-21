from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from keel.core import Budget, Ledger, Limits, Trace
from keel.recovery import validate_recovery
from keel.recovery_progress import RecoveryProgress
from keel.workspace import Workspace


def verification(regressions=1, targets=0, universe='a'):
    return [{'returncode': 1 if regressions or targets else 0, 'timeout': False,
             'stdout': json.dumps({'grading_status': 'graded',
                'failure_kind': 'test_failure' if regressions or targets else 'none',
                'test_universe_sha256': universe*64,
                'test_counts': {'PASS_TO_PASS': {'failure': regressions, 'success': 4-regressions},
                                'FAIL_TO_PASS': {'failure': targets, 'success': 2-targets}}})}]


class RecoveryProgressTests(unittest.TestCase):
    def workspace(self, root, ledger):
        return Workspace(root, Budget(Limits()), ledger, Trace(root/'trace.jsonl'))

    def begin(self, monitor, ledger, baseline):
        decision = {'action': 'replan', 'next_check': 'Determine which stage rejects the input.',
                    'hypothesis': 'Conversion may reject the input.'}
        fact = ledger.add('decision', 'critic', 'Untrusted recovery route', decision)
        monitor.begin(decision, baseline, fact)

    def test_records_new_evidence_without_claiming_the_check_was_executed(self):
        with tempfile.TemporaryDirectory() as temporary, closing(Ledger(Path(temporary)/'ledger.sqlite')) as ledger:
            root = Path(temporary); ws = self.workspace(root, ledger); monitor = RecoveryProgress(ws)
            old = ledger.add('file', 'scout', 'old source', {'text': 'old'})
            self.begin(monitor, ledger, verification())
            ledger.add('decision', 'implementer', 'I checked everything', 'unverified prose')
            evidence = ledger.add('file', 'scout', 'read_lines evidence', {'text': 'some source'})
            row = monitor.review(verification(), terminal_status='failed')
            self.assertEqual(row['observation_fact_ids'], [evidence])
            self.assertNotIn(old, row['observation_fact_ids'])
            self.assertEqual(row['check_execution'], 'not_established')
            self.assertEqual(row['verification_comparison']['status'], 'not_reverified')
            self.assertEqual(ws.budget.model_calls, 0)
            self.assertEqual(ws.budget.tool_calls, 0)
            self.assertEqual(len(monitor.report()['rounds']), 1)
            monitor.review(verification())
            self.assertEqual(len(monitor.report()['rounds']), 1)

    def test_only_matching_new_verifier_receipts_allow_comparison(self):
        for baseline, after, expected in (
                (verification(2), verification(1), 'improved'),
                (verification(1), verification(2), 'regressed'),
                (verification(1), verification(1), 'tied'),
                (verification(1), verification(0, universe='b'), 'incomparable')):
            with self.subTest(status=expected), tempfile.TemporaryDirectory() as temporary:
                with closing(Ledger(Path(temporary)/'ledger.sqlite')) as ledger:
                    ws = self.workspace(Path(temporary), ledger); monitor = RecoveryProgress(ws)
                    self.begin(monitor, ledger, baseline)
                    fact = ledger.add('test', 'verifier', 'Actual acceptance run', after[0])
                    row = monitor.review(after)
                    self.assertEqual(row['verification_comparison']['status'], expected)
                    self.assertEqual(row['verification_fact_ids'], [fact])
                    self.assertEqual(row['hypothesis_status'], 'unverified')

    def test_old_or_unrelated_results_do_not_count_as_revalidation(self):
        with tempfile.TemporaryDirectory() as temporary, closing(Ledger(Path(temporary)/'ledger.sqlite')) as ledger:
            monitor = RecoveryProgress(self.workspace(Path(temporary), ledger))
            ledger.add('test', 'verifier', 'Old matching result', verification()[0])
            self.begin(monitor, ledger, verification())
            ledger.add('test', 'verifier', 'Different result', verification(2)[0])
            self.assertEqual(monitor.review(verification())['verification_comparison']['status'], 'not_reverified')

    def test_option_is_explicit_and_bounded_to_adaptive_recovery(self):
        base = {'strategy': 'adaptive', 'max_actions': 4, 'write_roots': ['pkg']}
        self.assertTrue(validate_recovery({**base, 'monitor_progress': True})['monitor_progress'])
        for invalid in ({**base, 'monitor_progress': 'true'}, {'monitor_progress': True}):
            with self.assertRaises(ValueError):
                validate_recovery(invalid)
