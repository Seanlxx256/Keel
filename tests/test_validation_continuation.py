import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from examples.continue_index_validation import observation,has_progress,continue_run


class ValidationContinuationTests(unittest.TestCase):
    def test_only_known_index_budget_failure_is_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            rows=[dict(instance='index',status='failed',stage='baseline',error='Index wall-clock budget exhausted; checkpoints retained'),
                  dict(instance='coverage',status='failed',stage='baseline',error='Baseline did not pass coverage'),
                  dict(instance='unknown',status='failed',stage='baseline',error='Unknown error')]
            (root/'run.json').write_text(json.dumps(dict(status='incomplete',records=rows)))
            self.assertEqual(observation(root)['retryable'],['index'])

    def test_progress_does_not_count_repeated_error_or_elapsed_time(self):
        before=dict(completed=['first'],vectors={'task-2':100})
        self.assertFalse(has_progress(before,dict(before)))
        self.assertTrue(has_progress(before,dict(completed=['first'],vectors={'task-2':132})))
        self.assertTrue(has_progress(before,dict(completed=['first','second'],vectors={'task-2':0})))

    def test_coverage_only_stops_without_launch_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'run';run.mkdir()
            (run/'run.json').write_text(json.dumps(dict(status='incomplete',records=[
                dict(instance='coverage',status='failed',stage='baseline',error='Unindexed reference')])) )
            report=continue_run(root/'plan.json',run,root/'output',rounds=2,timeout=10)
            self.assertEqual(report['status'],'finished')
            self.assertEqual(report['rounds'],[])
            self.assertFalse((run/'continuation.lock').exists())

    def test_repeated_budget_error_without_progress_stops_after_one_round(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'run';run.mkdir()
            (run/'run.json').write_text(json.dumps(dict(status='incomplete',records=[
                dict(instance='index',status='failed',stage='baseline',error='Index wall-clock budget exhausted')])) )
            fake=SimpleNamespace(returncode=0,wait=lambda **kwargs:0)
            import subprocess
            module=SimpleNamespace(Popen=lambda *args,**kwargs:fake,DEVNULL=subprocess.DEVNULL,
                STDOUT=subprocess.STDOUT)
            with patch('examples.continue_index_validation.subprocess',module):
                report=continue_run(root/'plan.json',run,root/'output',rounds=3,timeout=10)
            self.assertEqual(len(report['rounds']),1)
            self.assertEqual(report['status'],'stopped')
            self.assertFalse(report['rounds'][0]['progress'])


if __name__=='__main__':
    unittest.main()
