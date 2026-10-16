import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples import run_transition_task as runner
from keel.evaluation_protocol import file_hash
from tests.test_httpx_1588 import matrix


class TrialTests(unittest.TestCase):
    def test_prepare_freezes_strategy_without_model_calls_or_operator_localization(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = root/'.keel/independent-snapshots/encode--httpx'/('a'*40)
            snapshot.mkdir(parents=True)
            (snapshot/'module.py').write_bytes(b'def value(): return 1\n')
            package = root/'package'
            package.mkdir()
            (package/'manifest.json').write_text('{}')
            (package/'acceptance.py').write_text('assert True')
            model = root/'model.json'
            model.write_text(json.dumps({'provider': 'ollama', 'name': 'fixture'}))
            task = {'id': 'httpx-1588', 'base_commit': 'a'*40, 'goal': 'Repair compatibility'}
            manifest = {'curator_receipt': {'base_inventory': runner.inventory(snapshot)},
                'acceptance': {'image': 'sha256:'+'b'*64}}
            with patch.object(runner, 'load_package', return_value=(manifest, task)), patch.object(
                    runner, 'implementation_hashes', return_value={}), patch.object(runner, 'from_config') as factory:
                for strategy in ('agent', 'localized-proposal'):
                    output = root/strategy
                    frozen = runner.prepare(root, package, model, output, strategy=strategy)
                    self.assertEqual(frozen['strategy'], strategy)
                    self.assertEqual(frozen['config']['mode'], strategy)
                    self.assertNotIn('proposal', frozen['config'])
                    self.assertNotIn('work_items', frozen['config'])
                    self.assertEqual(frozen['config']['budget']['max_model_calls'], 30)
                    self.assertFalse((output/'execution-started.json').exists())
                factory.return_value.complete.assert_not_called()
                factory.return_value.complete_json.assert_not_called()
                factory.return_value.check_credentials.assert_not_called()
            with self.assertRaises(ValueError):
                runner.prepare(root, package, model, root/'bad', strategy='other')

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
