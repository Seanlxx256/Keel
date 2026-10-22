from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from keel.core import Budget, BudgetExceeded, Ledger, Limits, PolicyDenied, RecoveryStopped, Trace
from keel.models import Reply
from keel.proposals import collect_evidence
from keel.recovery import RecoveryController
from keel.workspace import Workspace


class AcquisitionTests(unittest.TestCase):
    def exercise(self, *, second_unknown=False, insufficient=False, limit=10, edit_test=False):
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();(root/'.keel').mkdir();(root/'tests').mkdir()
            source=root/'render.py';source.write_bytes(b'def render(value):\n    return str(value)\n')
            test=root/'tests/test_render.py';test.write_bytes(b'def test_render():\n    assert render("a") == "A"\n')
            before=source.read_bytes();test_before=test.read_bytes()
            workspace=Workspace(root,Budget(Limits(max_tokens=200000,max_model_calls=limit)),ledger,Trace(root/'.keel/trace.jsonl'))
            controller=RecoveryController({'strategy':'adaptive','max_actions':6,'write_roots':['.'],
                                           'diagnostic_handoff':True},workspace)
            question='Inspect render.py and tests/test_render.py to determine the expected conversion.'
            controller.current_decision={'next_check':question,'hypothesis':'Return conversion is incomplete'}
            controller.current_verification=[{'stdout':json.dumps({'failed_tests':[{'test':'tests/test_render.py::test_render'}]})}]
            evidence=collect_evidence(workspace,{'files':['render.py'],'queries':['render']})
            class Model:
                calls=0
                proposals=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content']);properties=kwargs['schema']['properties']
                    if 'edits' in properties:
                        self.proposals+=1
                        unknown=self.proposals==1 or second_unknown
                        citations=[]
                        if not unknown:
                            row=data['readonly_diagnostic_evidence'][0]
                            citations=[{'path':row['path'],'sha256':row['sha256'],'quote':row['windows'][0]['text']}]
                        value={'summary':'Need evidence' if unknown else 'Uppercase returned string',
                            'edits':[] if unknown else [{'path':'tests/test_render.py' if edit_test else 'render.py',
                                'old':'return str(value)','new':'return str(value).upper()'}],
                            'diagnostic_answer':{'question':question,'status':'unknown' if unknown else 'source_answer',
                                'answer':'Missing assertion body' if unknown else 'The test requires uppercase output; uppercase conversion is absent',
                                'hypothesis_update':'undetermined' if unknown else 'supported',
                                'missing_evidence':'Need the failing test assertion' if unknown else '', 'citations':citations}}
                    elif 'outcome' in properties:
                        row=next(x for x in data['observations'] if x.get('path')=='tests/test_render.py' and 'text' in x)
                        value={'outcome':'insufficient' if insufficient else 'supported','evidence_ids':[row['fact_id']],
                            'assessment':'The assertion expects uppercase text','next_step':'Need runtime output' if insufficient else 'Correct conversion',
                            'checks':[]}
                    else:
                        value={'checks':[{'path':'tests/test_render.py','start_line':1,'end_line':2}]}
                    return Reply(json.dumps(value),10)
            model=Model();error=None
            try:controller.propose(model,workspace,'Fix conversion',['render.py'],evidence,{'max_context_bytes':24000})
            except (RecoveryStopped,BudgetExceeded,PolicyDenied) as exc:error=exc
            return error,source.read_bytes()!=before,test.read_bytes()==test_before,model.calls,controller.report()

    def test_unknown_reads_actual_test_then_reproposes_with_readonly_citation(self):
        error,changed,test_unchanged,calls,report=self.exercise()
        self.assertIsNone(error);self.assertTrue(changed);self.assertTrue(test_unchanged);self.assertEqual(calls,4)
        self.assertEqual(len(report['evidence_acquisitions']),1)

    def test_repeated_unknown_stops_after_one_acquisition_without_writes(self):
        error,changed,test_unchanged,calls,_=self.exercise(second_unknown=True)
        self.assertIsInstance(error,RecoveryStopped);self.assertFalse(changed);self.assertTrue(test_unchanged);self.assertEqual(calls,4)

    def test_insufficient_inspection_does_not_request_speculative_patch(self):
        error,changed,test_unchanged,calls,_=self.exercise(insufficient=True)
        self.assertIsInstance(error,RecoveryStopped);self.assertFalse(changed);self.assertTrue(test_unchanged);self.assertEqual(calls,3)

    def test_global_budget_is_not_reset_for_acquisition(self):
        error,changed,test_unchanged,calls,_=self.exercise(limit=1)
        self.assertIsInstance(error,BudgetExceeded);self.assertEqual(calls,1);self.assertFalse(changed);self.assertTrue(test_unchanged)

    def test_readonly_test_citation_does_not_grant_write_permission(self):
        error,changed,test_unchanged,_,_=self.exercise(edit_test=True)
        self.assertIsInstance(error,PolicyDenied);self.assertFalse(changed);self.assertTrue(test_unchanged)
