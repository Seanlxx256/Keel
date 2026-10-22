from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from keel.core import Budget, Ledger, Limits, RecoveryStopped, Trace
from keel.models import Reply
from keel.proposals import _propose_once, collect_evidence, InvalidProposal, proposal_request
from keel.workspace import Workspace


class DiagnosticAnswerTests(unittest.TestCase):
    def exercise(self, mutate=None):
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();(root/'.keel').mkdir()
            file=root/'render.py';file.write_text('def render(value):\n    return str(value)\n',encoding='utf-8')
            ws=Workspace(root,Budget(Limits(max_tokens=100000)),ledger,Trace(root/'.keel/trace.jsonl'))
            evidence=collect_evidence(ws,{'files':['render.py'],'queries':['render']})
            check={'next_check':'Does render uppercase its result?', 'hypothesis':'Uppercasing is missing'}
            response={'summary':'Uppercase result','edits':[{'path':'render.py','old':'return str(value)',
                'new':'return str(value).upper()'}], 'diagnostic_answer':{
                'question':check['next_check'],'status':'source_answer',
                'answer':'The return expression lacks uppercasing; uppercase that expression.',
                'hypothesis_update':'supported','missing_evidence':'',
                'citations':[{'path':'render.py','sha256':evidence[0]['sha256'],'quote':'return str(value)'}]}}
            if mutate: mutate(response)
            class Model:
                def complete_json(self,messages,**kwargs):
                    self.data=json.loads(messages[1]['content'])
                    return Reply(json.dumps(response),10)
            before=file.read_bytes(); error=None
            try: _propose_once(Model(),ws,'Fix rendering',['render.py'],evidence,{},diagnostic_check=check)
            except (InvalidProposal,RecoveryStopped) as exc: error=exc
            return error,before,file.read_bytes(),ws.budget.model_calls

    def test_source_answer_applies_real_change_in_same_call(self):
        error,before,after,calls=self.exercise()
        self.assertIsNone(error);self.assertNotEqual(before,after);self.assertEqual(calls,1)

    def test_comment_only_proposal_cannot_claim_diagnostic_repair(self):
        def change(r):r['edits']=[{'path':'render.py','old':'return str(value)','new':'# inspected\n    return str(value)'}]
        error,before,after,calls=self.exercise(change)
        self.assertIsInstance(error,InvalidProposal);self.assertIn('comments/formatting',str(error));self.assertEqual(before,after)

    def test_unknown_preserves_specific_blocker_and_does_not_write(self):
        def change(r):
            r['edits']=[];r['diagnostic_answer'].update(status='unknown',hypothesis_update='undetermined',
                missing_evidence='Need actual output from isolated execution; this interface has no executor')
        error,before,after,calls=self.exercise(change)
        self.assertIsInstance(error,RecoveryStopped);self.assertIn('isolated execution',str(error));self.assertEqual(before,after);self.assertEqual(calls,1)

    def test_unknown_with_edits_is_protocol_error(self):
        def change(r):r['diagnostic_answer'].update(status='unknown',hypothesis_update='undetermined',missing_evidence='Need runtime output')
        error,before,after,_=self.exercise(change)
        self.assertIsInstance(error,InvalidProposal);self.assertEqual(before,after)

    def test_fabricated_quote_or_wrong_question_never_writes(self):
        def quote(r):r['diagnostic_answer']['citations'][0]['quote']='invented source'
        def question(r):r['diagnostic_answer']['question']='A different question'
        for mutate in (quote,question):
            error,before,after,_=self.exercise(mutate)
            self.assertIsInstance(error,InvalidProposal);self.assertEqual(before,after)

    def test_prompt_explicitly_allows_unknown_without_edits(self):
        messages,schema,_=proposal_request('Fix',['x.py'],[{'path':'x.py','windows':[]}],{},
            diagnostic_check={'next_check':'Inspect input','hypothesis':'Unknown'})
        self.assertIn('edits=[]',messages[0]['content'])
        self.assertEqual(schema['properties']['edits']['minItems'],0)
        self.assertIn('diagnostic_answer',schema['required'])
