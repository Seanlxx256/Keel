import json
import tempfile
import time
import unittest
from pathlib import Path
from examples.evaluate_diagnosis import run_probe, trial, GUIDANCE
from keel.models import Reply
from keel.outer_validation_cases import FAMILIES_V2, EVIDENCE_PROTOCOL
from keel.outer_improvement import select, execute


class OuterValidationTests(unittest.TestCase):
    def test_new_fixtures_reproduce_same_symptom_but_discriminate_causes(self):
        for name, distinguishing in [('routing', 'resolve_primary'), ('snapshot', 'stored_copy')]:
            family = FAMILIES_V2[name]
            for cause in ('A', 'B'):
                self.assertFalse(run_probe(family, cause, 'original_failure'))
            self.assertNotEqual(run_probe(family, 'A', distinguishing),
                                run_probe(family, 'B', distinguishing))
        self.assertTrue(run_probe(FAMILIES_V2['snapshot'], 'A', 'input_control'))
        self.assertTrue(run_probe(FAMILIES_V2['snapshot'], 'B', 'input_control'))

    def test_explicit_contract_reaches_incumbent_and_candidate_without_oracle(self):
        owner = self
        class Model:
            def complete_json(self, messages, **kwargs):
                public = json.loads(messages[1]['content'])
                owner.assertEqual(public['evidence_contract'], EVIDENCE_PROTOCOL)
                owner.assertNotIn('sources', public)
                owner.assertNotIn('oracle_A', json.dumps(messages))
                return Reply(json.dumps({'action': 'conclude', 'probe_id': '', 'conclusion': 'undetermined',
                     'predicted_A': False, 'predicted_B': False, 'evidence_ids': [], 'reason': 'No observation yet.'}), 10)
        with tempfile.TemporaryDirectory() as temp:
            for index, guidance in enumerate([GUIDANCE['baseline'], 'Frozen candidate']):
                trial(Model(), FAMILIES_V2['routing'], 'A', 'baseline', Path(temp)/str(index),
                      time.monotonic()+30, guidance=guidance, protocol_extra=EVIDENCE_PROTOCOL)

    def test_tied_candidates_are_reported_without_claiming_unique_winner(self):
        cases = [('r1', '', ''), ('r2', '', '')]
        candidates = [{'id': 'a'}, {'id': 'b'}]
        rows = [{'case': case[0], 'arm': arm, 'passed': arm != 'incumbent'}
                for case in cases for arm in ('incumbent', 'a', 'b')]
        result = select(rows, candidates, cases=cases)
        self.assertEqual(result['eligible_tied_best'], ['a', 'b'])
        self.assertFalse(result['production_promoted'])

    def test_validation_repeats_frozen_candidates_without_proposal_and_resumes(self):
        class Model:
            calls = 0
            def complete_json(self, messages, **kwargs):
                self.calls += 1
                assert 'Propose at most' not in messages[0]['content']
                return Reply(json.dumps({'action': 'conclude', 'probe_id': '', 'conclusion': 'undetermined',
                     'predicted_A': False, 'predicted_B': False, 'evidence_ids': [], 'reason': 'Insufficient evidence.'}), 10)
        model = Model()
        validation = {'source': {'receipt': 'fixed'}, 'candidates': [{'id': 'fixed', 'guidance': 'Frozen guidance'}]}
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'run'
            result = execute(model, output, config_hash='fixed', max_seconds=120, validation=validation)
            self.assertEqual(model.calls, 20)
            self.assertEqual(result['budget']['model_calls'], 20)
            self.assertEqual(result['summary']['fixed']['cases'], 10)
            self.assertEqual(result['selection']['retained'], 'incumbent')
            execute(model, output, config_hash='fixed', max_seconds=120, validation=validation, resume=True)
            self.assertEqual(model.calls, 20)
