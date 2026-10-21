import json
from pathlib import Path
import tempfile
import unittest

from examples.run_frozen_model_review import execute
from keel.evaluation_protocol import file_hash
from keel.models import Reply


class FrozenReviewTests(unittest.TestCase):
    def test_single_followup_does_not_repeat_completed_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path, fields = self.prepare(root)
            plan = json.loads(path.read_text()); plan['requests'] = plan['requests'][1:]
            path.write_text(json.dumps(plan)); path.with_suffix('.sha256').write_text(file_hash(path))
            class Model:
                calls = 0
                def complete_json(self, *args, **kwargs):
                    self.calls += 1
                    return Reply(json.dumps({f: 'stop' if f == 'action' else 'unverified' for f in fields}), 30)
            model = Model(); report = execute(path, root/'out', model=model)
            self.assertEqual(model.calls, 1)
            self.assertEqual(len(report['records']), 1)

    def prepare(self, root):
        fields = ['action', 'reason', 'hypothesis', 'evidence', 'next_check', 'previous_attempt_assessment']
        plan = {'frozen_files': {}, 'requests': [
            {'arm': arm, 'messages': [{'role': 'user', 'content': 'diagnose'}],
             'schema': {'required': fields}} for arm in ('summary', 'source')],
            'scope': 'fixture review only'}
        path = root/'plan.json'; path.write_text(json.dumps(plan))
        path.with_suffix('.sha256').write_text(file_hash(path))
        return path, fields

    def test_completed_pair_reuses_receipts_without_new_paid_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan, fields = self.prepare(root)
            class Model:
                calls = 0
                def complete_json(self, *args, **kwargs):
                    self.calls += 1
                    return Reply(json.dumps({f: 'stop' if f == 'action' else 'unverified' for f in fields}), 30)
            model = Model()
            report = execute(plan, root/'out', model=model)
            self.assertEqual(model.calls, 2)
            self.assertIsNone(report['automatic_quality_score'])
            execute(plan, root/'out', model=model)
            self.assertEqual(model.calls, 2)
            (root/'out/summary.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'receipt mismatch'):
                execute(plan, root/'out', model=model)
            self.assertEqual(model.calls, 2)

    def test_interrupted_or_invalid_response_is_not_automatically_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan, _ = self.prepare(root)
            class Model:
                calls = 0
                def complete_json(self, *args, **kwargs):
                    self.calls += 1
                    return Reply('{}', 10)
            model = Model()
            with self.assertRaisesRegex(ValueError, 'Invalid Critic'):
                execute(plan, root/'out', model=model)
            with self.assertRaisesRegex(ValueError, 'automatic retry disabled'):
                execute(plan, root/'out', model=model)
            self.assertEqual(model.calls, 1)
            record = json.loads((root/'out/summary.json').read_text())
            self.assertEqual(record['raw_response'], '{}')
            self.assertEqual(record['budget']['tokens'], 10)


if __name__ == '__main__':
    unittest.main()
