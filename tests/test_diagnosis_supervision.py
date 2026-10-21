from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import unittest

from keel.core import Budget, BudgetExceeded, Ledger, Limits, Trace, InvalidSelection, RecoveryStopped
from keel.models import Reply
from keel.recovery import RecoveryController, validate_recovery
from keel.diagnosis_supervision import evidence_catalog, validate_review
from keel.workspace import Workspace


def diagnosis(claim='The later edit caused the first save failure.'):
    return {'action': 'repair', 'reason': 'Check observed error', 'hypothesis': claim,
            'evidence': 'A test failure was observed', 'next_check': 'Inspect save input',
            'previous_attempt_assessment': 'No runtime probe yet'}


def conflict():
    return {'verdict': 'conflict', 'assessment': 'The claimed order conflicts with the caller.',
            'findings': [{'claim_field': 'hypothesis',
                'claim_quote': 'The later edit caused the first save failure.',
                'evidence_id': 'verification:0:caller:0', 'evidence_quote': 'save_initial()',
                'conflict': 'The observed initial call fails before the later edit can execute.'}]}


def consistent():
    return {'verdict': 'consistent', 'assessment': 'No conflict identified; not proof of root cause.', 'findings': []}


class Scripted:
    def __init__(self, replies): self.replies = replies; self.calls = []
    def complete_json(self, messages, **kwargs):
        self.calls.append(messages)
        return Reply(json.dumps(self.replies[len(self.calls)-1]), 10)


class SupervisionTests(unittest.TestCase):
    def verification(self):
        return [{'returncode': 1, 'stdout': json.dumps({'failure_kind': 'test_failure',
            'failure_locations': [{'status': 'observed', 'source_path': 'checks/test_store.py',
                'line': 12, 'statement': 'save_initial()', 'context': '> save_initial()'}],
            'failure_excerpts': ['E   ValueError: invalid token']})}]

    def controller(self, root, ledger, calls=10):
        ws = Workspace(root, Budget(Limits(max_model_calls=calls, max_tokens=200000)), ledger, Trace(root/'trace.jsonl'))
        config = {'strategy': 'adaptive', 'max_actions': 4, 'write_roots': ['.'],
                  'monitor_progress': True, 'diagnosis_supervision': True}
        return RecoveryController(config, ws)

    def test_conflict_gets_one_correction_then_recheck_in_shared_budget(self):
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'ledger.sqlite')) as ledger:
            controller = self.controller(Path(temp), ledger)
            corrected = diagnosis('The initial save rejects its input; the later edit has not run.')
            model = Scripted([diagnosis(), conflict(), corrected, consistent()])
            result = controller.decide(model, 'Preserve valid save behavior', [], self.verification(),
                                       {'max_context_bytes': 24000})
            self.assertEqual(result, corrected)
            self.assertEqual(controller.ws.budget.model_calls, 4)
            self.assertEqual(controller.ws.budget.tokens, 40)
            self.assertEqual(controller.ws.budget.tool_calls, 0)
            self.assertIn('consistency_review', json.loads(model.calls[2][1]['content']))
            self.assertEqual(controller.progress.pending['decision_fact_id'], controller._last_decision_fact)
            self.assertEqual(len(controller.report()['supervision_reviews']), 2)
            reviewer = json.loads(model.calls[1][1]['content'])
            self.assertEqual(set(reviewer), {'diagnosis', 'evidence'})

    def test_persistent_conflict_stops_instead_of_review_loop(self):
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'ledger.sqlite')) as ledger:
            controller = self.controller(Path(temp), ledger)
            model = Scripted([diagnosis(), conflict(), diagnosis(), conflict()])
            with self.assertRaisesRegex(RecoveryStopped, 'after one correction'):
                controller.decide(model, 'Investigate', [], self.verification(), {'max_context_bytes': 24000})
            self.assertEqual(len(model.calls), 4)
            self.assertIsNone(controller.progress.pending)

    def test_budget_does_not_reset_for_correction(self):
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'ledger.sqlite')) as ledger:
            controller = self.controller(Path(temp), ledger, calls=2)
            model = Scripted([diagnosis(), conflict()])
            with self.assertRaises(BudgetExceeded):
                controller.decide(model, 'Investigate', [], self.verification(), {'max_context_bytes': 24000})
            self.assertEqual(len(model.calls), 2)

    def test_correction_may_stop_without_another_review_chain(self):
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'ledger.sqlite')) as ledger:
            controller = self.controller(Path(temp), ledger)
            stopped = {**diagnosis(), 'action': 'stop', 'reason': 'Cannot distinguish remaining causes safely'}
            model = Scripted([diagnosis(), conflict(), stopped])
            result = controller.decide(model, 'Investigate', [], self.verification(), {'max_context_bytes': 24000})
            self.assertEqual(result['action'], 'stop')
            self.assertEqual(len(model.calls), 3)

    def test_fabricated_claim_or_evidence_quote_is_rejected(self):
        observation = {'failed_verification': [{'feedback': {
            'failure_locations': [{'statement': 'save_initial()'}]}}]}
        catalog = evidence_catalog(observation)
        for field, text in (('claim_quote', 'not in diagnosis'), ('evidence_id', 'invented'),
                            ('evidence_quote', 'not observed')):
            with self.subTest(field=field):
                value = conflict(); value['findings'][0][field] = text
                with self.assertRaises(InvalidSelection): validate_review(value, diagnosis(), catalog)

    def test_non_conflict_findings_and_empty_conflict_are_rejected_explicitly(self):
        catalog = evidence_catalog({'failed_verification': [{'feedback': {
            'failure_locations': [{'statement': 'save_initial()'}]}}]})
        for verdict in ('consistent', 'insufficient'):
            value = {**conflict(), 'verdict': verdict}
            with self.assertRaisesRegex(InvalidSelection, 'requires findings='):
                validate_review(value, diagnosis(), catalog)
        value = {**consistent(), 'verdict': 'conflict'}
        with self.assertRaisesRegex(InvalidSelection, 'requires at least one'):
            validate_review(value, diagnosis(), catalog)

    def test_added_quote_marks_are_not_silently_stripped(self):
        catalog = evidence_catalog({'failed_verification': [{'feedback': {
            'failure_locations': [{'statement': 'save_initial()'}]}}]})
        value = conflict(); value['findings'][0]['evidence_quote'] = '"save_initial()"'
        with self.assertRaises(InvalidSelection): validate_review(value, diagnosis(), catalog)

    def test_consistent_and_insufficient_are_advisory_not_task_success(self):
        for verdict in ('consistent', 'insufficient'):
            with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'ledger.sqlite')) as ledger:
                controller = self.controller(Path(temp), ledger)
                review = {**consistent(), 'verdict': verdict}
                model = Scripted([diagnosis(), review])
                result = controller.decide(model, 'Investigate', [], self.verification(), {'max_context_bytes': 24000})
                self.assertEqual(result['action'], 'repair')
                self.assertEqual(len(model.calls), 2)
                self.assertNotIn('passed', controller.report())

    def test_opt_in_validation_and_default_off(self):
        with self.assertRaises(ValueError): validate_recovery({'diagnosis_supervision': True})
        with self.assertRaises(ValueError): validate_recovery({'diagnosis_supervision': 'yes'})
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'ledger.sqlite')) as ledger:
            root = Path(temp); ws = Workspace(root, Budget(Limits()), ledger, Trace(root/'trace.jsonl'))
            controller = RecoveryController({'max_actions': 2}, ws)
            model = Scripted([diagnosis()])
            controller.decide(model, 'Investigate', [], self.verification(), {'max_context_bytes': 24000})
            self.assertEqual(len(model.calls), 1)

    def test_runtime_can_repair_after_supervised_correction(self):
        from keel.runtime import run
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'app.py').write_bytes(b'def value():\n    return 1\n')
            def patch(before, after):
                return {'summary': 'Change value', 'edits': [
                    {'path': 'app.py', 'old': 'return '+str(before), 'new': 'return '+str(after)}]}
            wrong = diagnosis(); wrong['evidence'] = 'The test passed'
            review = {'verdict': 'conflict', 'assessment': 'Claim contradicts test result', 'findings': [{
                'claim_field': 'evidence', 'claim_quote': 'The test passed',
                'evidence_id': 'verification:0:stderr', 'evidence_quote': 'AssertionError',
                'conflict': 'The acceptance assertion failed.'}]}
            model = Scripted([{'files': ['app.py']}, {'locations': ['app.py:1']}, patch(1, 2),
                              wrong, review, diagnosis('The value is still wrong'), consistent(), patch(2, 3)])
            config = {'mode': 'localized-proposal', 'goal': 'Return 3',
                'agent': {'max_context_bytes': 24000}, 'budget': {'max_tokens': 300000, 'max_model_calls': 12},
                'recovery': {'strategy': 'adaptive', 'write_roots': ['.'], 'max_actions': 4,
                             'diagnosis_supervision': True},
                'acceptance': [[sys.executable, '-B', '-c', 'import app; assert app.value() == 3']]}
            result = run(config, root, root/'.keel/run', model=model)
            self.assertEqual(result['status'], 'passed', result.get('failure'))
            self.assertEqual(result['budget']['model_calls'], 8)
            self.assertEqual(len(result['verification_attempts']), 2)
            self.assertEqual(len(result['recovery']['supervision_reviews']), 2)
