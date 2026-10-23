import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.evaluation_protocol import file_hash
from keel.probe_preflight import check_imports


class ImportPreflightTests(unittest.TestCase):
    def plan(self, root):
        source=root/'candidate.py';source.write_bytes(b'value=1\n')
        plan={'source_files':{'sample/value.py':str(source)},'edit_files':['sample/value.py'],
              'frozen_files':{str(source):file_hash(source)},'probe_image':'sha256:fixture','probe_python':'/python'}
        path=root/'plan.json';path.write_text(json.dumps(plan));path.with_suffix('.sha256').write_text(file_hash(path))
        return path,file_hash(source)

    def test_pass_requires_candidate_loader_provenance_not_only_zero_returncode(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,sha=self.plan(root)
            marker=[{'module':'sample.value','sha256':sha,'status':'executed'}]
            result={'outcome':'completed','probe':{
                'stdout':json.dumps({'module':'sample.value','file':'/workspace/sample/value.py','package':'sample'}),
                'stderr':'__KEEL_CANDIDATE_IMPORTS__'+json.dumps(marker)}}
            with patch('keel.probe_preflight.run_probe',return_value=result) as run:
                report=check_imports(plan,root/'out')
                self.assertEqual(report['status'],'passed');self.assertEqual(report['model_calls'],0)
                self.assertTrue(report['workspace_unchanged']);self.assertTrue(run.call_args.kwargs['candidate_imports'])
                self.assertIn("importlib.import_module(name)",report['check_code'])
                with self.assertRaises(FileExistsError):check_imports(plan,root/'out')
            self.assertEqual(report['budget']['model_calls'],0)

    def test_zero_returncode_without_marker_is_provenance_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,_=self.plan(root)
            with patch('keel.probe_preflight.run_probe',return_value={'outcome':'completed',
                    'probe':{'stdout':'','stderr':''}}):
                self.assertEqual(check_imports(plan,root/'out')['status'],'provenance_failed')

    def test_script_import_failure_and_docker_unavailability_remain_distinct(self):
        for outcome,status in [('script_failed','import_failed'),('executor_failed','execution_unavailable')]:
            with self.subTest(outcome=outcome),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);plan,_=self.plan(root)
                with patch('keel.probe_preflight.run_probe',return_value={'outcome':outcome}):
                    self.assertEqual(check_imports(plan,root/'out')['status'],status)

    def test_changed_frozen_source_rejected_before_docker(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,_=self.plan(root);(root/'candidate.py').write_text('value=2')
            with patch('keel.probe_preflight.run_probe') as run:
                with self.assertRaisesRegex(ValueError,'source changed'):check_imports(plan,root/'out')
                run.assert_not_called()
