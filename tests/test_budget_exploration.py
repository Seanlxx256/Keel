from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.campaign_reporting import FrozenModel
from keel.core import Ledger, BudgetExceeded
from keel.models import Reply
from test_diagnosis_supervision import SupervisionTests, Scripted, diagnosis, consistent


class BudgetExplorationTests(unittest.TestCase):
    def test_bad_supervisor_reply_can_correct_without_resetting_budget(self):
        helper = SupervisionTests()
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'ledger.sqlite')) as ledger:
            controller = helper.controller(Path(temp), ledger)
            controller.budget_driven = True
            model = Scripted([diagnosis(), {'bad': 'reply'}, consistent()])
            result = controller.decide(model, 'Repair', [], helper.verification(), {'max_context_bytes': 24000})
            self.assertEqual(result, diagnosis())
            self.assertEqual(controller.ws.budget.model_calls, 3)
            self.assertIn('host_validation_feedback', str(model.calls[-1]))

    def test_repeated_local_failure_allowed_but_global_budget_still_stops(self):
        helper = SupervisionTests()
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'ledger.sqlite')) as ledger:
            controller = helper.controller(Path(temp), ledger, calls=2)
            controller.budget_driven = True
            model = Scripted([diagnosis(), {'bad': 'reply'}, {'bad': 'again'}])
            with self.assertRaises(BudgetExceeded):
                controller.decide(model, 'Repair', [], helper.verification(), {'max_context_bytes': 24000})
            self.assertEqual(controller.ws.budget.model_calls, 2)

    def test_transcript_preserves_request_before_interrupted_reply(self):
        class Broken:
            def complete(self, messages, **kwargs):
                raise RuntimeError('provider failed')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'model.jsonl'
            model = FrozenModel(Broken(), lambda: None, path)
            with self.assertRaises(RuntimeError):
                model.complete([{'role': 'user', 'content': 'inspect source'}])
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([row['event'] for row in rows], ['request', 'error'])

    def test_deadline_stops_child_without_retry(self):
        from examples.run_bounded_exploration import execute
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root/'plan.json'
            plan.write_text(json.dumps({'root': temp, 'implementation': {}, 'output': str(root/'trial'),
                'python': 'python', 'arguments': [], 'max_seconds': 1}))
            with patch('examples.run_bounded_exploration.implementation_hashes', return_value={}), \
                    patch('examples.run_bounded_exploration.subprocess.Popen') as launch, \
                    patch('examples.run_bounded_exploration.time.monotonic', side_effect=[0, 2, 3]), \
                    patch('examples.run_bounded_exploration.stop_tree') as stop:
                launch.return_value.poll.side_effect = [None, 1, 1]
                self.assertEqual(execute(plan), 1)
                self.assertEqual(launch.call_count, 1)
                stop.assert_called_once()
            self.assertEqual(json.loads((root/'watchdog.json').read_text())['status'], 'deadline_exceeded')
