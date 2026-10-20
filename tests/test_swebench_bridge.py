import json
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import sys
import unittest
from unittest.mock import patch

from examples.swebench_bridge import grade, run_harness,grade_snapshot
from keel.swebench import prepare, verify_task, export_prediction, reference_prediction, grading_outcome
from keel.swebench_transport import linux_artifact_writes


class SwebenchBridgeTests(unittest.TestCase):
    def test_saved_snapshot_grades_without_restarting_agent_or_overwriting_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root)
            repo=root/'repo';repo.mkdir();(repo/'app.py').write_bytes(b'VALUE=2\n')
            reference=root/'reference';reference.mkdir();(reference/'grading.json').write_text('{}')
            with patch('examples.run_swebench_task.check_reference',return_value=None), \
                 patch('examples.run_swebench_task.reference_policies',return_value={'network_policy':'no_pipeline'}), \
                 patch('examples.swebench_verify_workspace.workspace_patch',return_value='VALID_GIT_DIFF'), \
                 patch('examples.swebench_bridge.subprocess.run',return_value=SimpleNamespace(stdout='app.py\n')), \
                 patch('examples.swebench_bridge.grade',return_value={'status':'graded','official_resolved':False}) as grader:
                report=grade_snapshot(root/'task',repo,reference,root/'salvage',python='python',timeout=600)
            self.assertEqual(report['model_calls'],0)
            self.assertFalse(report['official_resolved'])
            self.assertEqual(grader.call_args.kwargs['network_policy'],'no_pipeline')
            prediction=json.loads((root/'salvage/snapshot-export/predictions.jsonl').read_text())
            self.assertEqual(prediction['model_patch'],'VALID_GIT_DIFF')
            self.assertEqual(json.loads((root/'run/result.json').read_text())['status'],'failed')
    def test_harness_default_file_encoding_is_utf8_even_if_parent_disables_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            command = [sys.executable, '-c', "from pathlib import Path; Path('unicode.txt').write_text(chr(0x263a)); print('done')"]
            with patch.dict('os.environ', {'PYTHONUTF8': '0'}), contextlib.redirect_stdout(io.StringIO()):
                result = run_harness(command, cwd=root, log_path=root/'harness.log', timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertEqual((root/'unicode.txt').read_bytes(), '\u263a'.encode('utf-8'))
    def test_linux_artifacts_disable_windows_translation_and_restore_writer(self):
        original = Path.write_text
        calls = []
        def writer(path, data, **kwargs):
            calls.append((path, data, kwargs))
            return len(data)
        with patch.object(Path, 'write_text', writer):
            with linux_artifact_writes():
                Path('eval.sh').write_text('set -e\necho ok\n')
                Path('patch.diff').write_text('a\nb\n')
                Path('report.json').write_text('{}')
            self.assertIs(Path.write_text, writer)
        self.assertIs(Path.write_text, original)
        self.assertEqual(calls[0][1], 'set -e\necho ok\n')
        self.assertEqual(calls[0][2]['newline'], '\n')
        self.assertEqual(calls[1][2]['newline'], '\n')
        self.assertIsNone(calls[2][2]['newline'])

    def test_linux_shell_bytes_have_no_crlf(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'eval.sh'
            content = 'set -uxo pipefail\ncd /testbed\n'
            with linux_artifact_writes():
                target.write_text(content)
            self.assertEqual(target.read_bytes(), content.encode('utf-8'))
    def test_real_child_output_is_teed_and_quiet_period_has_heartbeat(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            console = io.StringIO()
            command = [sys.executable, '-u', '-c', 'import time; print("begin",flush=True); time.sleep(0.2); print("end",flush=True)']
            with contextlib.redirect_stdout(console):
                result = run_harness(command, cwd=root, log_path=root/'harness.log', timeout=5, heartbeat=0.05)
            self.assertEqual(result.returncode, 0)
            self.assertIn('begin', console.getvalue())
            self.assertIn('process alive', console.getvalue())
            self.assertIn('end', (root/'harness.log').read_text())
    def fixture(self, root):
        row = {'instance_id': 'org__lib-1', 'repo': 'org/lib', 'base_commit': 'a'*40,
               'problem_statement': 'Fix the issue', 'patch': 'SECRET_GOLD', 'test_patch': 'SECRET_TEST',
               'FAIL_TO_PASS': ['secret_case'], 'hints_text': 'SECRET_HINT'}
        dataset = root/'data.jsonl'
        dataset.write_text(json.dumps(row)+'\n', encoding='utf-8')
        prepare(dataset, row['instance_id'], root/'task')
        run = root/'run'
        run.mkdir()
        (run/'result.json').write_text(json.dumps({'goal': row['problem_statement'], 'status': 'failed',
                                                  'failure': {'category': 'verification_failed'}}))
        (run/'changes.patch').write_text('--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-a\n+b\n')
        return row, run

    def test_solver_input_excludes_answers_and_failed_runs_are_not_dropped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            row, run = self.fixture(root)
            task = (root/'task/solver-task.json').read_text()
            self.assertNotIn('SECRET', task)
            self.assertNotIn('FAIL_TO_PASS', task)
            receipt = export_prediction(root/'task', run, root/'export', 'keel-test')
            self.assertEqual(receipt['runtime_status'], 'failed')
            self.assertIsNone(receipt['official_resolved'])
            self.assertEqual(json.loads((root/'export/predictions.jsonl').read_text())['instance_id'], row['instance_id'])

    def test_drift_and_wrong_goal_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, run = self.fixture(root)
            (run/'result.json').write_text('{"goal":"Another issue","status":"passed"}')
            with self.assertRaisesRegex(ValueError, 'goal'):
                export_prediction(root/'task', run, root/'export', 'keel')
            (root/'task/grader-dataset.jsonl').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'changed'):
                verify_task(root/'task')

    def test_reference_is_labelled_and_not_an_agent_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            receipt = reference_prediction(root/'task', root/'reference')
            self.assertEqual(receipt['runtime_status'], 'reference_only')
            self.assertEqual(json.loads((root/'reference/predictions.jsonl').read_text())['model_patch'], 'SECRET_GOLD')

    def test_exit_zero_without_report_is_not_resolved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, run = self.fixture(root)
            export_prediction(root/'task', run, root/'export', 'keel')
            with patch('examples.swebench_bridge.run_harness', return_value=SimpleNamespace(returncode=0)):
                result = grade(root/'task', root/'export', root/'grading')
            self.assertEqual(result['status'], 'grading_error')
            self.assertIsNone(result['official_resolved'])

    def test_interruption_does_not_leave_running_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, run = self.fixture(root)
            export_prediction(root/'task', run, root/'export', 'keel')
            with patch('examples.swebench_bridge.run_harness', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    grade(root/'task', root/'export', root/'grading')
            result = json.loads((root/'grading/grading.json').read_text())
            self.assertEqual(result['status'], 'interrupted')
            self.assertIsNone(result['official_resolved'])

    def test_official_report_overrides_runtime_success_or_process_exit(self):
        self.assertFalse(grading_outcome({'id': {'resolved': False}}, 'id')['official_resolved'])
        for report in ({}, {'id': {'resolved': 'true'}}, {'id': {'resolved': True}}):
            with self.assertRaises(ValueError):
                grading_outcome(report, 'id')

    def test_grading_reads_only_fresh_run_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, run = self.fixture(root)
            export_prediction(root/'task', run, root/'export', 'keel')
            def harness(command, **kwargs):
                dataset = Path(command[command.index('--dataset_name')+1])
                data = json.loads(dataset.read_text(encoding='utf-8'))
                self.assertIsInstance(data, list)
                self.assertEqual(data[0]['patch'], 'SECRET_GOLD')
                run_id = command[command.index('--run_id')+1]
                report = kwargs['cwd']/'logs/evaluation'/run_id/'keel/org__lib-1/report.json'
                report.parent.mkdir(parents=True)
                report.write_text(json.dumps({'org__lib-1': {'resolved': True, 'patch_successfully_applied': True}}))
                return SimpleNamespace(returncode=0)
            with patch('examples.swebench_bridge.run_harness', side_effect=harness):
                result = grade(root/'task', root/'export', root/'grading')
            self.assertEqual(result['status'], 'graded')
            self.assertTrue(result['official_resolved'])
            self.assertEqual(result['runtime_status'], 'failed')

    def test_new_harness_with_classic_dataset_stops_before_subprocess(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, run = self.fixture(root)
            export_prediction(root/'task', run, root/'export', 'keel')
            with patch('examples.swebench_bridge.importlib.metadata.version', return_value='5.0.2'), \
                 patch('examples.swebench_bridge.run_harness') as harness:
                result = grade(root/'task', root/'export', root/'grading')
            harness.assert_not_called()
            self.assertEqual(result['status'], 'grading_error')
            self.assertIn('schema', result['error'])

    def test_classic_harness_report_directory_is_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, run = self.fixture(root)
            export_prediction(root/'task', run, root/'export', 'keel')
            def harness(command, **kwargs):
                run_id = command[command.index('--run_id')+1]
                report = kwargs['cwd']/'logs/run_evaluation'/run_id/'keel/org__lib-1/report.json'
                report.parent.mkdir(parents=True)
                report.write_text(json.dumps({'org__lib-1': {'resolved': False}}))
                return SimpleNamespace(returncode=0)
            with patch('examples.swebench_bridge.importlib.metadata.version', return_value='3.0.0'), \
                 patch('examples.swebench_bridge.run_harness', side_effect=harness):
                result = grade(root/'task', root/'export', root/'grading')
            self.assertEqual(result['status'], 'graded')
            self.assertFalse(result['official_resolved'])
