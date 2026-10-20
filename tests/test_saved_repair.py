import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from keel.evaluation_protocol import file_hash
from keel.saved_repair import load_saved_repair


class SavedRepairTests(unittest.TestCase):
    def fixture(self, root):
        task, ref, snapshot, repo = [root/name for name in ('task','ref','snapshot','repo')]
        for path in (task,ref,snapshot,repo):
            path.mkdir()
        (repo/'module.py').write_text('VALUE = 1\n')
        (task/'grader-dataset.jsonl').write_text(json.dumps({'instance_id':'toy'}))
        (ref/'grading.json').write_text('{}')
        grading=snapshot/'grading'
        log=grading/'logs/run_evaluation/run/model/toy'
        log.mkdir(parents=True)
        (grading/'grader-input.json').write_text(json.dumps([{'instance_id':'toy'}]))
        (log/'report.json').write_text(json.dumps({'toy': {'tests_status': {'FAIL_TO_PASS': {'failure':['test_value']}}}}))
        (log/'test_output.txt').write_text('>>>>> Start Test Output\nE AssertionError: wrong value\n>>>>> End Test Output')
        grade={'status':'graded','official_resolved':False,'runtime_status':'saved_snapshot_only',
               'report_sha256':file_hash(log/'report.json')}
        (grading/'grading.json').write_text(json.dumps(grade))
        receipt={'status':'graded','official_resolved':False,'grading':grade,
                 'reference_grade_sha256':file_hash(ref/'grading.json'),
                 'source_files':{'module.py':file_hash(repo/'module.py')},
                 'patch_sha256':hashlib.sha256(b'saved diff').hexdigest()}
        (snapshot/'snapshot-grade.json').write_text(json.dumps(receipt))
        return task,ref,snapshot,repo

    def test_loads_observed_failure_and_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp))
            with patch('keel.saved_repair.verify_task',return_value={'instance_id':'toy'}), patch('keel.saved_repair.workspace_patch',return_value='saved diff'):
                diff,context=load_saved_repair(*args)
                self.assertEqual(diff,'saved diff')
                self.assertIn('wrong value',str(context['verification']))
                (args[-1]/'module.py').write_text('VALUE = 2\n')
                with self.assertRaisesRegex(ValueError,'source changed'):
                    load_saved_repair(*args)

    def test_rejects_report_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp))
            next((args[2]/'grading/logs').rglob('report.json')).write_text('{}')
            with patch('keel.saved_repair.verify_task',return_value={'instance_id':'toy'}), patch('keel.saved_repair.workspace_patch',return_value='saved diff'):
                with self.assertRaisesRegex(ValueError,'report changed'):
                    load_saved_repair(*args)
