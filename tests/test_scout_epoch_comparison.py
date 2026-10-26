import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from examples.run_scout_epoch_comparison import execute


class ScoutEpochComparisonTests(unittest.TestCase):
    def test_completed_negative_endpoints_do_not_promote_or_select(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);evaluation=root/'evaluation.json'
            evaluation.write_text(json.dumps({'status':'completed','summary':{'adapter':{'contract_valid':0}}}))
            plan={'output':str(root/'result'),'max_seconds':10,'stages':[{'name':'fixed','command':['fixture'],'cap_seconds':1}],
                'evaluation_reports':{'fixed':str(evaluation)}}
            path=root/'plan.json';path.write_text(json.dumps(plan))
            with patch('examples.run_scout_epoch_comparison.observed_stage',return_value={'returncode':0,'timeout':False}):
                result=execute(path)
            self.assertEqual(result['status'],'completed');self.assertFalse(result['production_promoted'])
            self.assertIsNone(result['selected_checkpoint'])

    def test_stage_failure_persists_incomplete_receipt_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'plan.json';path.write_text(json.dumps({'output':str(root/'result'),'max_seconds':10,
                'stages':[{'name':'train','command':['fixture'],'cap_seconds':1}],'evaluation_reports':{}}))
            with patch('examples.run_scout_epoch_comparison.observed_stage',return_value={'returncode':1,'timeout':False}) as stage:
                with self.assertRaisesRegex(RuntimeError,'train'):execute(path)
            self.assertEqual(stage.call_count,1)
            self.assertEqual(json.loads((root/'result/report.json').read_text())['status'],'incomplete')
