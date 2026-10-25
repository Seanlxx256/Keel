import json
import tempfile
import unittest
from pathlib import Path
from examples.evaluate_diagnosis import digest
from keel.models import Reply
from keel.outer_feedback import collect_feedback
from keel.outer_improvement import execute, select
from keel.outer_validation_cases import CASES_V2


def source_fixture(root):
    root.mkdir()
    candidates = [{'id': 'old', 'guidance': 'Old candidate'}]
    proposal = {'source': 'frozen'}
    manifest = {'config_sha256': 'fixed'}
    cases = [(f'repeat-{r}-{name}', family, cause)
             for r in (1, 2) for name, family, cause in CASES_V2]
    rows = []
    for name, family, cause in cases:
        for arm in ('incumbent', 'old'):
            passed = family == 'counter_control'
            score = {'passed': passed, 'correct_conclusion': passed,
                     'correct_counterfactual_predictions': passed}
            row = {'case': name, 'arm': arm, 'passed': passed, 'metrics': score}
            rows.append(row)
            output = root/(name+'-'+arm); output.mkdir()
            record = {'status': 'completed', 'steps': [], 'observations': [], 'score': score}
            raw = json.dumps(record).encode(); (output/'trial.json').write_bytes(raw)
            import hashlib
            (output/'receipt.json').write_text(json.dumps({'trial_sha256': hashlib.sha256(raw).hexdigest()}), encoding='utf-8')
    report = {'status': 'completed', 'manifest_sha256': digest(manifest), 'records': rows,
              'selection': select(rows, candidates, cases=cases)}
    for name, value in [('report', report), ('manifest', manifest), ('candidates', candidates),
                        ('proposal', proposal), ('proposal-receipt', {'proposal': digest(proposal), 'candidates': digest(candidates)})]:
        (root/(name+'.json')).write_text(json.dumps(value), encoding='utf-8')


class OuterFeedbackTests(unittest.TestCase):
    def test_collection_checks_all_receipts_and_excludes_oracle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'source'; source_fixture(root)
            feedback = collect_feedback(root, 'fixed')
            self.assertEqual(len(feedback['cases']), 3)
            self.assertEqual(len({c[1] for c in feedback['cases']}), 3)
            self.assertNotIn('oracle_A', json.dumps(feedback['examples']))
            self.assertNotIn('sources', json.dumps(feedback['examples']))
            with self.assertRaisesRegex(ValueError, 'matching completed'):
                collect_feedback(root, 'wrong')
            trial = next(root.glob('*/trial.json')); trial.write_bytes(trial.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'receipt mismatch'):
                collect_feedback(root, 'fixed')

    def test_one_proposal_real_probe_comparison_and_no_paid_resume(self):
        owner = self
        class Model:
            calls = 0
            def complete_json(self, messages, **kwargs):
                self.calls += 1
                if 'Propose at most one' in messages[0]['content']:
                    owner.assertEqual(kwargs['schema']['properties']['candidates']['maxItems'], 1)
                    owner.assertIn('development_trajectories', messages[1]['content'])
                    owner.assertNotIn('oracle_A', json.dumps(messages))
                    return Reply(json.dumps({'candidates': [{'id': 'consistent', 'guidance': 'Check field consistency.'}]}), 10)
                if len(messages) == 2:
                    public = json.loads(messages[1]['content'])
                    probe = next(iter(public['available_probes']))
                    value = {'action': 'probe', 'probe_id': probe, 'predicted_A': False,
                             'predicted_B': True, 'conclusion': 'undetermined', 'evidence_ids': [], 'reason': 'Compare alternatives.'}
                else:
                    observation = json.loads(messages[-1]['content'])['observation']
                    value = {'action': 'conclude', 'probe_id': '', 'predicted_A': False,
                             'predicted_B': False, 'conclusion': 'B' if observation['result'] else 'A',
                             'evidence_ids': [observation['id']], 'reason': 'Observed result.'}
                return Reply(json.dumps(value), 10)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source_fixture(root/'source')
            feedback = collect_feedback(root/'source', 'fixed')
            model = Model()
            result = execute(model, root/'output', config_hash='fixed', max_seconds=120, feedback=feedback)
            self.assertEqual(result['budget']['model_calls'], 13)
            self.assertEqual(result['budget']['tool_calls'], 12)
            self.assertEqual(result['selection']['retained'], 'incumbent')
            execute(model, root/'output', config_hash='fixed', max_seconds=120, feedback=feedback, resume=True)
            self.assertEqual(model.calls, 13)
            self.assertEqual(result['budget']['limits']['max_model_calls'], 19)
            with self.assertRaisesRegex(ValueError, '300 seconds'):
                execute(model, root/'bad', config_hash='fixed', max_seconds=301, feedback=feedback)
