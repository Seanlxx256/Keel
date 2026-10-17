import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from examples.run_swebench_task import config_for, check_reference
from examples.swebench_verify_workspace import workspace_patch, verify
from keel.swebench import prepare
from keel.evaluation_protocol import file_hash
from keel.runtime import validate


class SwebenchTaskTests(unittest.TestCase):
    def task(self, root):
        row = {'instance_id': 'org__lib-1', 'repo': 'org/lib', 'base_commit': 'a'*40,
               'problem_statement': 'Repair API behavior', 'patch': 'SECRET_GOLD', 'test_patch': 'SECRET_TEST'}
        source = root/'data.jsonl'
        source.write_text(json.dumps(row))
        prepare(source, row['instance_id'], root/'task')
        return row

    def test_config_uses_issue_only_and_official_feedback_loop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = self.task(root)
            config = config_for(task, root/'task', root/'trial', {'name': 'test'}, 'harness-python')
            self.assertEqual(config['goal'], task['problem_statement'])
            self.assertNotIn('SECRET', json.dumps(config))
            self.assertEqual(config['recovery']['strategy'], 'adaptive')
            self.assertEqual(config['verification_repair_attempts'], 3)
            self.assertIn('swebench_verify_workspace.py', config['acceptance'][0][1])
            validate(config)

    def test_unverified_reference_cannot_start_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.task(root)
            (root/'reference').mkdir()
            (root/'reference/grading.json').write_text(json.dumps({'status': 'graded', 'official_resolved': False}))
            with self.assertRaisesRegex(ValueError, 'preflight'):
                check_reference(root/'task', root/'reference')

    def test_empty_patch_does_not_call_harness_or_claim_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.task(root)
            with patch('examples.swebench_verify_workspace.workspace_patch', return_value=''), \
                 patch('examples.swebench_verify_workspace.grade') as grade:
                result = verify(root, root/'task', root/'verification', 'python')
            grade.assert_not_called()
            self.assertFalse(result['official_resolved'])

    def test_feedback_excludes_setup_and_test_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.task(root)
            def grade(task, export, output, **kwargs):
                directory = output/'logs/run_evaluation/run/keel-verification/org__lib-1'
                directory.mkdir(parents=True)
                (directory/'report.json').write_text(json.dumps({'org__lib-1': {'tests_status': {'FAIL_TO_PASS': {'failure': ['case']}}}}))
                (directory/'test_output.txt').write_text('SECRET_TEST_PATCH\n>>>>> Start Test Output\ncase failed\n>>>>> End Test Output\nSETUP_SECRET')
                return {'status': 'graded', 'official_resolved': False, 'run_id': 'run'}
            with patch('examples.swebench_verify_workspace.workspace_patch', return_value='source diff'), \
                 patch('examples.swebench_verify_workspace.grade', side_effect=grade):
                feedback = verify(root, root/'task', root/'verification', 'python')
            self.assertNotIn('SECRET', json.dumps(feedback))
            self.assertIn('case failed', feedback['observed_test_output_tail'])

    def test_real_git_diff_is_bound_to_exact_base_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.run(['git', '-c', 'safe.directory='+str(root), '-C', str(root), *args],
                                      check=True, capture_output=True).stdout.decode().strip()
            git('init', '-q')
            (root/'app.py').write_text('VALUE = 1\n')
            git('add', 'app.py')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
            task = {'base_commit': git('rev-parse', 'HEAD')}
            (root/'app.py').write_text('VALUE = 2\n')
            diff = workspace_patch(root, task)
            self.assertIn('-VALUE = 1', diff)
            self.assertIn('+VALUE = 2', diff)
            with self.assertRaisesRegex(ValueError, 'HEAD'):
                workspace_patch(root, {'base_commit': 'b'*40})
