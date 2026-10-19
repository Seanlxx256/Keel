import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.run_frozen_retrieval_validation import exposure_registry, verify_plan, execute, bounded_index


class FrozenValidationTests(unittest.TestCase):
    def test_index_subprocess_is_killed_at_deadline(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            process = MagicMock()
            process.poll.return_value = None
            launcher = MagicMock()
            launcher.__enter__.return_value = process
            with patch('examples.run_frozen_retrieval_validation.subprocess.Popen', return_value=launcher), \
                    patch('examples.run_frozen_retrieval_validation.time.monotonic', side_effect=[0, 100]):
                with self.assertRaises(TimeoutError):
                    bounded_index(root, root, 'test', 1)
            process.kill.assert_called_once()

    def test_registry_excludes_failed_and_only_planned_tasks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prior = root/'.keel/swe-public/prior'
            prior.mkdir(parents=True)
            (prior/'plan.json').write_text(json.dumps({'instances': [dict(id='owner__repo-1')]}))
            (prior/'result.json').write_text(json.dumps({'instances': [
                dict(instance_id='owner__repo-2', status='failed')]}))
            # Dataset population is not an exposure registry.
            corpus = root/'.keel/datasets/swe'
            corpus.mkdir(parents=True)
            (corpus/'result.json').write_text(json.dumps({'instance_id': 'owner__repo-3'}))
            excluded, receipts = exposure_registry(root)
            self.assertEqual(excluded, {'owner__repo-1', 'owner__repo-2'})
            self.assertEqual(len(receipts), 2)

    def test_changed_plan_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'plan.json'
            path.write_text('{}')
            path.with_suffix('.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest())
            path.write_text('{"changed": true}')
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                verify_plan(path)

    def test_failed_snapshots_are_retained_without_replacement_or_scores(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root/'plan.json'
            plan.write_text('{}')
            tasks = [dict(instance_id=f'owner__repo-{i}', repository='owner/repo', base_commit='a'*40)
                     for i in (1, 2)]
            with patch('examples.run_frozen_retrieval_validation.verify_plan',
                       return_value={'tasks': tasks, 'policy': {}}), \
                    patch('examples.run_frozen_retrieval_validation.prepare_snapshot',
                          side_effect=OSError('offline')) as prepare, \
                    patch('examples.run_frozen_retrieval_validation.compare') as compare:
                result = execute(root, plan, root/'run')
            self.assertEqual(prepare.call_count, 2)
            compare.assert_not_called()
            self.assertEqual(result['status'], 'no_runnable_tasks')
            self.assertEqual(result['planned_tasks'], 2)
            self.assertEqual(result['baseline_ready_tasks'], 0)
            self.assertEqual([r['instance_id'] for r in result['records']], [t['instance_id'] for t in tasks])
            self.assertTrue(all(r['status'] == 'infrastructure_failed' for r in result['records']))
            self.assertNotIn('summary', result)


if __name__ == '__main__':
    unittest.main()
