import json
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.run_local_regression import execute


class LocalRegressionRunnerTests(unittest.TestCase):
    def setup_plan(self,temp):
        root=Path(temp);output=root/'absent'/'results';plan=root/'plan.json'
        plan.write_text(json.dumps({'root':str(root),'output':str(output),
            'implementation':{},'input_hashes':{},'modules':['fixture_not_imported']}))
        return plan,output

    def test_result_sink_precedes_test_import_and_final_report_survives(self):
        with tempfile.TemporaryDirectory() as temp:
            plan,output=self.setup_plan(temp)
            def load(names):
                self.assertEqual(json.loads((output/'report.json').read_text())['status'],'running')
                return unittest.TestSuite([unittest.FunctionTestCase(lambda:None)])
            with patch('examples.run_local_regression.unittest.defaultTestLoader.loadTestsFromNames',side_effect=load):
                console=io.StringIO()
                with redirect_stdout(console):report=execute(plan)
            self.assertEqual(report['status'],'passed')
            self.assertEqual(len(report['test_inventory']),1)
            self.assertNotIn('test_inventory',json.loads(console.getvalue().splitlines()[-1]))
            self.assertEqual(json.loads((output/'report.json').read_text())['tests_run'],1)

    def test_prior_results_are_not_overwritten_or_tests_dispatched(self):
        with tempfile.TemporaryDirectory() as temp:
            plan,output=self.setup_plan(temp);output.mkdir(parents=True)
            with patch('examples.run_local_regression.unittest.defaultTestLoader.loadTestsFromNames') as load:
                with self.assertRaises(FileExistsError):execute(plan)
            load.assert_not_called()

    def test_import_interruption_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            plan,output=self.setup_plan(temp)
            with patch('examples.run_local_regression.unittest.defaultTestLoader.loadTestsFromNames',side_effect=RuntimeError('fixture')):
                with self.assertRaises(RuntimeError):execute(plan)
            self.assertEqual(json.loads((output/'report.json').read_text())['status'],'interrupted')
