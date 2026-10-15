import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples import run_transition_task as runner
from keel.evaluation_protocol import file_hash
from tests.test_httpx_1588 import matrix


class TrialTests(unittest.TestCase):
    def test_acceptance_requires_cases_versions_and_backend(self):
        runs = matrix()
        expected = json.loads(runs['gold_new']['stdout'])
        expected['cases'] = [r['case'] for r in expected.pop('records')]
        self.assertTrue(runner.accepted(runs['gold_new'], expected))
        self.assertTrue(runner.baseline_matches(runs['base_new'], expected))
        self.assertFalse(runner.accepted(runs['base_new'], expected))
        expected['versions']['httpcore'] = '0.12.3'
        self.assertFalse(runner.accepted(runs['gold_new'], expected))
        self.assertFalse(runner.baseline_matches(runs['base_new'], expected))

    def test_interrupted_or_completed_attempt_cannot_run_again(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output/'repo').mkdir()
            (output/'prepared.json').write_text(json.dumps({'source': {}, 'implementation': {}}))
            (output/'prepared.sha256').write_text(file_hash(output/'prepared.json'))
            (output/'execution-started.json').write_text('{}')
            with patch.object(runner, 'implementation_hashes', return_value={}):
                with self.assertRaises(FileExistsError):
                    runner.execute(output, output)
            (output/'prepared.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'manifest changed'):
                runner.execute(output, output)

    def test_changed_source_rejected_before_attempt_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output/'repo').mkdir()
            (output/'repo/a.py').write_text('changed')
            (output/'prepared.json').write_text(json.dumps({'source': {}, 'implementation': {}}))
            (output/'prepared.sha256').write_text(file_hash(output/'prepared.json'))
            with patch.object(runner, 'implementation_hashes', return_value={}):
                with self.assertRaisesRegex(ValueError, 'source changed'):
                    runner.execute(output, output)
            self.assertFalse((output/'execution-started.json').exists())
