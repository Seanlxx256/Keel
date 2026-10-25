import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keel.models import Reply
from keel.outer_improvement import execute, select, validate_candidates
from examples.evaluate_diagnosis import CASES


class OuterImprovementTests(unittest.TestCase):
    def test_protected_config_duplicate_and_path_candidates_rejected(self):
        for value in ({'candidates': [], 'limits': {}},
                      {'candidates': [{'id': '../escape', 'guidance': 'x'}]},
                      {'candidates': [{'id': 'x', 'guidance': 'x', 'tools': []}]},
                      {'candidates': [{'id': 'x', 'guidance': 'x'}]*2}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_candidates(value)

    def test_no_gain_and_regression_reject_all_even_with_higher_total(self):
        candidates = [{'id': 'candidate', 'guidance': 'x'}]
        def rows(a, b):
            return [{'case': case[0], 'arm': arm, 'passed': values[i]}
                    for arm, values in [('incumbent', a), ('candidate', b)]
                    for i, case in enumerate(CASES)]
        for before, after in [([True, False, False, False], [False, True, True, True]),
                              ([True]*4, [True]*4)]:
            self.assertEqual(select(rows(before, after), candidates)['retained'], 'incumbent')
        decision = select(rows([False]*4, [True]*4), candidates)
        self.assertEqual(decision['retained'], 'candidate')
        self.assertFalse(decision['production_promoted'])
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            select([], candidates)

    def test_real_isolated_probes_full_selection_and_no_paid_resume(self):
        class Model:
            calls = 0
            def complete_json(self, messages, **kwargs):
                self.calls += 1
                assert 'oracle_A' not in json.dumps(messages)
                if 'Propose at most' in messages[0]['content']:
                    return Reply(json.dumps({'candidates': [{'id': 'evidence',
                                  'guidance': 'Use a discriminating probe, then cite its result.'}]}), 10)
                improved = messages[0]['content'].startswith('Use a discriminating')
                if not improved:
                    value = {'action': 'conclude', 'probe_id': '', 'conclusion': 'A',
                             'predicted_A': True, 'predicted_B': False,
                             'evidence_ids': [], 'reason': 'Unsupported guess.'}
                elif len(messages) == 2:
                    reader = 'read_value' in messages[1]['content']
                    value = {'action': 'probe', 'probe_id': 'decode_spaced' if reader else 'select_zero',
                             'conclusion': 'undetermined', 'predicted_A': reader,
                             'predicted_B': not reader, 'evidence_ids': [], 'reason': 'Distinguish causes.'}
                else:
                    observed = json.loads(messages[-1]['content'])['observation']
                    reader = 'read_value' in messages[1]['content']
                    cause = ('A' if observed['result'] else 'B') if reader else ('B' if observed['result'] else 'A')
                    value = {'action': 'conclude', 'probe_id': '', 'conclusion': cause,
                             'predicted_A': True, 'predicted_B': False,
                             'evidence_ids': [observed['id']], 'reason': 'Observed discriminating result.'}
                return Reply(json.dumps(value), 10)
        model = Model()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'run'
            result = execute(model, output, config_hash='fixed', max_seconds=120)
            self.assertEqual(result['selection']['retained'], 'evidence')
            self.assertEqual(result['budget']['model_calls'], 13)
            self.assertEqual(result['budget']['tool_calls'], 8)
            self.assertEqual(len(result['records']), 8)
            resumed = execute(model, output, config_hash='fixed', max_seconds=120, resume=True)
            self.assertEqual(model.calls, 13)
            self.assertEqual(resumed['selection'], result['selection'])
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                execute(model, output, config_hash='changed', max_seconds=120, resume=True)
            arm = output/'case-1-incumbent'/'trial.json'
            arm.write_bytes(arm.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'receipt mismatch'):
                execute(model, output, config_hash='fixed', max_seconds=120, resume=True)

    def test_invalid_proposal_preserves_raw_reply_without_executing_cases(self):
        class Model:
            def complete_json(self, *args, **kwargs):
                return Reply('{"candidates":[],"limits":{}}', 10)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'run'
            with self.assertRaises(ValueError):
                execute(Model(), output, config_hash='fixed')
            self.assertTrue((output/'proposal.json').exists())
            report = json.loads((output/'report.json').read_text())
            self.assertEqual(report['status'], 'incomplete')
            self.assertEqual(report['budget']['model_calls'], 1)
            self.assertEqual(report['records'], [])
