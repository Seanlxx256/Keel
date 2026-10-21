from contextlib import closing
import json
import hashlib
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
    def test_named_definition_review_is_bounded_and_does_not_repeat_model_call(self):
        from keel.recovery import RecoveryController
        from keel.models import Reply
        with tempfile.TemporaryDirectory() as temporary, closing(Ledger(Path(temporary)/'ledger.sqlite')) as ledger:
            root = Path(temporary); ws = self.workspace(root, ledger)
            (root/'codec.py').write_bytes(b'def encode_value(x):\n    return str(x)\n')
            config = {'strategy': 'adaptive', 'max_actions': 4, 'write_roots': ['.'],
                      'monitor_progress': True, 'targeted_source_review': True}
            controller = RecoveryController(config, ws)
            class Model:
                def __init__(self): self.calls = []
                def complete_json(self, messages, **kwargs):
                    self.calls.append(json.loads(messages[1]['content']))
                    return Reply(json.dumps({'action': 'replan', 'reason': 'Need source',
                        'hypothesis': 'Tentative conversion problem', 'evidence': 'No runtime probe',
                        'next_check': 'Inspect encode_value and compare the stack frame with the setup phase',
                        'previous_attempt_assessment': 'No runtime evidence yet'}), 10)
            model = Model(); plan = [{'id': 'fix', 'files': ['codec.py']}]
            controller.decide(model, 'Resolve conversion error', plan, [], {'max_context_bytes': 24000})
            self.assertEqual(len(model.calls), 2)
            source = model.calls[1]['targeted_source_review']['windows'][0]
            self.assertIn('return str(x)', source['text'])
            self.assertEqual(source['symbol'], 'encode_value')
            self.assertEqual(ws.budget.model_calls, 2)
            self.assertEqual((root/'codec.py').read_bytes(), b'def encode_value(x):\n    return str(x)\n')
            controller.decide(model, 'Resolve conversion error', plan, [], {'max_context_bytes': 24000})
            self.assertEqual(len(model.calls), 3)
            (root/'codec.py').write_bytes(b'def encode_value(x):\n    return repr(x)\n')
            controller.decide(model, 'Resolve conversion error', plan, [], {'max_context_bytes': 24000})
            self.assertEqual(len(model.calls), 5)

    def test_targeted_review_requires_explicit_opt_in_and_progress(self):
        base = {'strategy': 'adaptive', 'max_actions': 4, 'write_roots': ['.']}
        for invalid in ({**base, 'targeted_source_review': True},
                        {**base, 'monitor_progress': True, 'targeted_source_review': 'yes'}):
            with self.assertRaises(ValueError): validate_recovery(invalid)
        self.assertNotIn('targeted_source_review', validate_recovery(base))

    def test_targeted_source_ignores_unmentioned_definitions_and_oversized_bodies(self):
        with tempfile.TemporaryDirectory() as temporary, closing(Ledger(Path(temporary)/'ledger.sqlite')) as ledger:
            root = Path(temporary); ws = self.workspace(root, ledger); monitor = RecoveryProgress(ws)
            (root/'fixture.py').write_bytes(b'def unrelated():\n    return 1\ndef target_value():\n    return 2\n')
            result = monitor.targeted_source('Inspect target_value', ['fixture.py'])
            self.assertEqual([w['symbol'] for w in result['windows']], ['target_value'])
            small = RecoveryProgress(ws).targeted_source('Inspect target_value', ['fixture.py'], max_bytes=10)
            self.assertEqual(small['windows'], [])
            self.assertEqual(small['omitted'][0]['reason'], 'complete_definition_exceeds_budget')

    def test_critic_request_contains_prior_source_and_preserves_unknown_check_status(self):
        from keel.recovery import RecoveryController
        from keel.models import Reply
        with tempfile.TemporaryDirectory() as temporary, closing(Ledger(Path(temporary)/'ledger.sqlite')) as ledger:
            root = Path(temporary); ws = self.workspace(root, ledger)
            controller = RecoveryController({'strategy': 'adaptive', 'max_actions': 4,
                'write_roots': ['.'], 'monitor_progress': True}, ws)
            source = 'def test_contract():\n    setup()\n    expect_error()\n'
            (root/'checks.py').write_bytes(source.encode())
            fact = ledger.add('file', 'scout', 'read_lines evidence', {
                'path': 'checks.py', 'start_line': 1, 'end_line': 3, 'text': source})
            controller.progress.rounds.append({'round': 1, 'question': 'Inspect test_contract',
                'observation_fact_ids': [fact], 'check_execution': 'not_established'})
            class Model:
                def complete_json(self, messages, **kwargs):
                    self.observation = json.loads(messages[1]['content'])
                    return Reply(json.dumps({'action': 'stop', 'reason': 'No safe next check',
                        'hypothesis': 'Unknown', 'evidence': 'Source seen, no probe executed',
                        'next_check': 'Need an authorized probe',
                        'previous_attempt_assessment': 'Read alone does not establish the hypothesis'}), 10)
            model = Model()
            controller.decide(model, 'Inspect contract', [], [], {'max_context_bytes': 18000})
            context = model.observation['previous_check_observations']
            self.assertEqual(context['source_handoff']['windows'][0]['text'], source)
            self.assertEqual(context['check_execution'], 'not_established')
            self.assertEqual(ws.budget.model_calls, 1)
            self.assertEqual(ws.budget.tool_calls, 1)

    def test_source_body_survives_rounds_and_changed_source_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temporary, closing(Ledger(Path(temporary)/'ledger.sqlite')) as ledger:
            root = Path(temporary); monitor = RecoveryProgress(self.workspace(root, ledger))
            source = 'def test_conversion():\n    setup()\n    expect_error()\n'
            (root/'checks.py').write_bytes(source.encode('utf-8'))
            fact = ledger.add('file', 'scout', 'read_lines evidence', {
                'path': 'checks.py', 'start_line': 1, 'end_line': 3, 'text': source})
            row = {'question': 'Inspect test_conversion setup and error phases.', 'observation_fact_ids': [fact]}
            monitor.rounds.append(row)
            later = {'question': row['question'], 'observation_fact_ids': []}
            context = monitor.context(later)
            window = context['source_handoff']['windows'][0]
            self.assertEqual(window['text'], source)
            self.assertEqual(window['fact_id'], fact)
            self.assertNotIn('check_execution', context['source_handoff'])
            (root/'checks.py').write_bytes(source.replace('expect_error()', 'expect_success()').encode('utf-8'))
            stale = monitor.context(later)['source_handoff']
            self.assertEqual(stale['windows'], [])
            self.assertEqual(stale['omitted'][0]['reason'], 'source_changed_or_unavailable')

    def test_handoff_does_not_cut_windows_or_read_unrelated_source(self):
        with tempfile.TemporaryDirectory() as temporary, closing(Ledger(Path(temporary)/'ledger.sqlite')) as ledger:
            root = Path(temporary); ws = self.workspace(root, ledger); monitor = RecoveryProgress(ws)
            source = 'def target_function():\n    return 1\n'
            (root/'source.py').write_bytes(source.encode('utf-8'))
            fact = ledger.add('file', 'scout', 'read_lines evidence', {
                'path': 'source.py', 'start_line': 1, 'end_line': 2, 'text': source})
            row = {'question': 'Inspect target_function', 'observation_fact_ids': [fact]}
            self.assertEqual(monitor.source_handoff(row, max_bytes=10)['windows'], [])
            self.assertEqual(ws.budget.tool_calls, 0)
            row['question'] = 'Inspect unrelated_identifier'
            self.assertEqual(monitor.source_handoff(row)['windows'], [])
            self.assertEqual(ws.budget.tool_calls, 0)

    def test_full_file_hash_rejects_change_outside_window_and_future_rounds(self):
        with tempfile.TemporaryDirectory() as temporary, closing(Ledger(Path(temporary)/'ledger.sqlite')) as ledger:
            root = Path(temporary); monitor = RecoveryProgress(self.workspace(root, ledger))
            source = 'def target_function():\n    return 1\n# old tail\n'
            (root/'source.py').write_bytes(source.encode())
            fact = ledger.add('file', 'scout', 'read_lines evidence', {
                'path': 'source.py', 'start_line': 1, 'end_line': 2,
                'text': ''.join(source.splitlines(True)[:2]),
                'source_sha256': hashlib.sha256(source.encode()).hexdigest()})
            row = {'round': 1, 'question': 'Inspect target_function', 'observation_fact_ids': []}
            monitor.rounds = [{'round': 2, 'observation_fact_ids': [fact]}]
            self.assertEqual(monitor.source_handoff(row)['windows'], [])
            row['observation_fact_ids'] = [fact]
            (root/'source.py').write_bytes(source.replace('old tail', 'new tail').encode())
            self.assertEqual(monitor.source_handoff(row)['omitted'][0]['reason'], 'source_changed_or_unavailable')

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
