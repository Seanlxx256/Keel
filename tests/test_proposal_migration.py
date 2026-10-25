import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from keel.models import Reply
from keel.outer_improvement import execute, validate_candidates
from keel.outer_feedback import collect_feedback
from tests.test_outer_feedback import source_fixture


class ProposalMigrationTests(unittest.TestCase):
    def test_safe_long_identifier_allowed_but_path_and_unbounded_names_rejected(self):
        value = {'candidates': [{'id': 'diagnostic_probe_precision', 'guidance': 'Keep fields consistent.'}]}
        self.assertEqual(validate_candidates(value)[0]['id'], 'diagnostic_probe_precision')
        for name in ('../escape', 'a'*65):
            with self.assertRaises(ValueError):
                validate_candidates({'candidates': [{'id': name, 'guidance': 'x'}]})

    def test_saved_paid_proposal_migrates_without_dispatch_and_carries_usage(self):
        class Model:
            calls = 0
            def complete_json(self, messages, **kwargs):
                self.calls += 1
                if 'Propose at most' in messages[0]['content']:
                    return Reply(json.dumps({'candidates': [{'id': 'diagnostic_probe_precision',
                                      'guidance': 'Keep fields consistent.'}]}), 10)
                return Reply(json.dumps({'action': 'conclude', 'probe_id': '', 'conclusion': 'undetermined',
                    'predicted_A': False, 'predicted_B': False, 'evidence_ids': [], 'reason': 'Insufficient evidence.'}), 10)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source_fixture(root/'validation')
            feedback = collect_feedback(root/'validation', 'fixed'); model = Model()
            with patch('keel.outer_improvement.validate_candidates', side_effect=ValueError('old name cap')):
                with self.assertRaises(ValueError):
                    execute(model, root/'failed', config_hash='fixed', max_seconds=120, feedback=feedback)
            before = {p.name: p.read_bytes() for p in (root/'failed').iterdir() if p.is_file()}
            result = execute(model, root/'migrated', config_hash='fixed', max_seconds=120,
                             feedback=feedback, reuse_proposal=root/'failed')
            self.assertEqual(model.calls, 7)
            self.assertEqual(result['budget']['model_calls'], 7)
            self.assertEqual(result['budget']['tokens'], 70)
            manifest = json.loads((root/'migrated'/'manifest.json').read_text(encoding='utf-8'))
            self.assertIn('proposal_reuse', manifest)
            self.assertEqual(before, {p.name: p.read_bytes() for p in (root/'failed').iterdir() if p.is_file()})
            execute(model, root/'migrated', config_hash='fixed', max_seconds=120,
                    feedback=feedback, reuse_proposal=root/'failed', resume=True)
            self.assertEqual(model.calls, 7)
            with self.assertRaisesRegex(ValueError, 'incompatible'):
                execute(model, root/'wrong', config_hash='changed', max_seconds=120,
                        feedback=feedback, reuse_proposal=root/'failed')
