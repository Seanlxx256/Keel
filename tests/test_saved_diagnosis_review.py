import json
from pathlib import Path
import tempfile
import unittest

from examples.review_saved_diagnosis import execute
from keel.evaluation_protocol import file_hash
from keel.models import ModelError
from tests.test_diagnosis_supervision import diagnosis, conflict, consistent, Scripted


class SavedDiagnosisReviewTests(unittest.TestCase):
    def test_invalid_review_has_detailed_error_and_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); p = self.prepare(root)
            invalid = {**conflict(), 'verdict': 'consistent'}
            model = Scripted([invalid])
            report = execute(p, root/'out', model=model)
            self.assertEqual(report['status'], 'incomplete')
            self.assertIn('requires findings=[]', report['validation_error'])
            with self.assertRaisesRegex(ValueError, 'no automatic paid retry'):
                execute(p, root/'out', model=model)
            self.assertEqual(len(model.calls), 1)

    def prepare(self, root):
        plan = {'frozen_files': {}, 'diagnosis': diagnosis(), 'goal': 'Investigate first save',
                'current_plan': [], 'verification': [{'returncode': 1, 'stdout': json.dumps({
                    'failure_kind': 'test_failure', 'failure_locations': [{'status': 'observed',
                    'source_path': 'checks/test_store.py', 'line': 12,
                    'statement': 'save_initial()', 'context': '> save_initial()'}]})}],
                'source_review': {'windows': []}, 'scope': 'Synthetic review fixture'}
        p = root/'plan.json'; p.write_text(json.dumps(plan))
        p.with_suffix('.sha256').write_text(file_hash(p)); return p

    def test_saved_reply_is_not_paid_and_receipts_reuse_complete_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); p = self.prepare(root)
            corrected = diagnosis('Initial save failed, before later edits')
            model = Scripted([conflict(), corrected, consistent()])
            report = execute(p, root/'out', model=model)
            self.assertEqual(report['status'], 'completed_needs_review')
            self.assertEqual(report['new_provider_calls'], 3)
            self.assertEqual(report['budget']['model_calls'], 4)
            self.assertEqual(report['budget']['tokens'], 30)
            self.assertEqual(report['final_diagnosis'], corrected)
            execute(p, root/'out', model=model)
            self.assertEqual(len(model.calls), 3)

    def test_failed_dispatch_preserved_without_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); p = self.prepare(root)
            class Unavailable:
                calls = 0
                def complete_json(self, *args, **kwargs):
                    self.calls += 1; raise ModelError('Fixture unavailable')
            model = Unavailable(); report = execute(p, root/'out', model=model)
            self.assertEqual(report['status'], 'incomplete')
            self.assertEqual(report['new_provider_calls'], 1)
            with self.assertRaisesRegex(ValueError, 'no automatic paid retry'):
                execute(p, root/'out', model=model)
            self.assertEqual(model.calls, 1)

    def test_credential_preflight_happens_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); p = self.prepare(root)
            class MissingKey:
                def check_credentials(self): raise ModelError('Missing fixture key')
            with self.assertRaises(ModelError): execute(p, root/'out', model=MissingKey())
            self.assertFalse((root/'out').exists())
