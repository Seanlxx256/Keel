import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from examples.evaluate_diagnosis import FAMILIES, load_completed, main, run_probe, score_trial, trial, validate_response
from keel.models import Reply


def response(action='probe', probe='decode_spaced', conclusion='undetermined', ids=None):
    return {'action': action, 'probe_id': probe, 'predicted_A': True, 'predicted_B': False,
            'conclusion': conclusion, 'evidence_ids': ids or [], 'reason': 'Compare isolated decoding.'}


class DiagnosisEvaluationTests(unittest.TestCase):
    def test_real_probes_distinguish_twins_but_repeating_symptom_does_not(self):
        for family_id, distinguishing, uninformative in (
                ('reader', 'decode_spaced', 'read_spaced'),
                ('counter', 'select_zero', 'original_failure')):
            family = FAMILIES[family_id]
            with self.subTest(family=family_id):
                self.assertNotEqual(run_probe(family, 'A', distinguishing),
                                    run_probe(family, 'B', distinguishing))
                self.assertFalse(run_probe(family, 'A', uninformative))
                self.assertFalse(run_probe(family, 'B', uninformative))

    def test_guess_or_wrong_predictions_cannot_pass(self):
        final = response('conclude', '', 'A', ['observation-1'])
        self.assertFalse(score_trial('A', [], final)['passed'])
        observation = {'id': 'observation-1', 'oracle_A': True, 'oracle_B': False,
                       'predicted_A': False, 'predicted_B': True}
        self.assertFalse(score_trial('A', [observation], final)['passed'])
        observation.update(predicted_A=True, predicted_B=False)
        self.assertTrue(score_trial('A', [observation], final)['passed'])
        final['evidence_ids'] = []
        self.assertFalse(score_trial('A', [observation], final)['passed'])

    def test_forged_citations_and_arbitrary_commands_rejected(self):
        for value in (response(probe='__import__("os").system("bad")'),
                      response(ids=['invented'])):
            with self.assertRaises(ValueError):
                validate_response(value, FAMILIES['reader']['probes'], set())

    def test_multi_turn_observation_is_real_and_oracle_is_hidden(self):
        owner = self
        class Model:
            calls = 0
            def complete_json(self, messages, **kwargs):
                self.calls += 1
                owner.assertNotIn('oracle_A', json.dumps(messages))
                if self.calls == 1:
                    value = response()
                else:
                    evidence = json.loads(messages[-1]['content'])['observation']
                    owner.assertEqual(evidence['result'], False)
                    value = response('conclude', '', 'B', [evidence['id']])
                return Reply(json.dumps(value), 10)
        with tempfile.TemporaryDirectory() as temporary:
            result = trial(Model(), FAMILIES['reader'], 'B', 'candidate',
                           Path(temporary)/'arm', time.monotonic()+60)
        self.assertTrue(result['score']['passed'])
        self.assertEqual(result['budget']['model_calls'], 2)
        self.assertEqual(result['budget']['tool_calls'], 2)

    def test_protocol_failure_is_failed_result_not_excluded_case(self):
        class Model:
            def complete_json(self, messages, **kwargs):
                return Reply(json.dumps(response(ids=['invented'])), 10)
        with tempfile.TemporaryDirectory() as temporary:
            result = trial(Model(), FAMILIES['reader'], 'A', 'baseline',
                           Path(temporary)/'arm', time.monotonic()+60)
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(result['score']['passed'])
        self.assertEqual(result['budget']['tool_calls'], 0)

    def test_repeat_stops_without_charging_another_probe(self):
        class Model:
            def complete_json(self, messages, **kwargs):
                return Reply(json.dumps(response(probe='read_spaced')), 10)
        with tempfile.TemporaryDirectory() as temporary:
            result = trial(Model(), FAMILIES['reader'], 'A', 'candidate',
                           Path(temporary)/'arm', time.monotonic()+60)
        self.assertFalse(result['score']['passed'])
        self.assertEqual(result['budget']['tool_calls'], 2)

    def test_full_pair_resume_reuses_completed_arms_and_rejects_tampering(self):
        class Model:
            calls = 0
            def complete_json(self, messages, **kwargs):
                self.calls += 1
                if len(messages) == 2:
                    return Reply(json.dumps(response()), 10) if 'read_value' in messages[-1]['content'] else Reply(
                        json.dumps({**response(probe='select_zero'), 'predicted_A': False, 'predicted_B': True}), 10)
                observed = json.loads(messages[-1]['content'])['observation']
                reader = 'read_value' in messages[1]['content']
                cause = ('A' if observed['result'] else 'B') if reader else ('B' if observed['result'] else 'A')
                return Reply(json.dumps(response('conclude', '', cause, [observed['id']])), 10)
        model = Model()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); config = root/'config.json'; config.write_text('{}')
            output = root/'evaluation'
            arguments = ['evaluate_diagnosis', '--model-config', str(config), '--output', str(output), '--execute']
            with patch('examples.evaluate_diagnosis.from_config', return_value=model), patch('sys.argv', arguments):
                main()
            self.assertEqual(model.calls, 16)
            with patch('examples.evaluate_diagnosis.from_config', return_value=model), patch('sys.argv', arguments+['--resume']):
                main()
            self.assertEqual(model.calls, 16)
            report = json.loads((output/'report.json').read_text())
            self.assertEqual(report['summary']['candidate']['passed'], 4)
            arm = output/'case-1-baseline'
            (arm/'trial.json').write_bytes((arm/'trial.json').read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'receipt mismatch'):
                load_completed(arm)
