import json
from pathlib import Path
import tempfile
import unittest

from examples.review_saved_diagnosis import execute
from keel.evaluation_protocol import file_hash
from keel.models import Reply
from keel.proposals import source_evidence


class AcquisitionReviewTests(unittest.TestCase):
    def prepare(self, root):
        source=root/'source.py';source.write_bytes(b'def render(value):\n    return str(value)\n')
        check='Inspect render.py return conversion.'
        diagnosis={'action':'replan','reason':'Need source','hypothesis':'Uppercasing missing','evidence':'Observed lowercase',
                   'next_check':check,'previous_attempt_assessment':'Need to inspect return'}
        saved={'summary':'Need source','edits':[], 'diagnostic_answer':{'question':check,'status':'unknown',
            'answer':'Need the return expression','hypothesis_update':'undetermined',
            'missing_evidence':'Read the return expression','citations':[]}}
        plan={'mode':'diagnostic_acquisition','scope':'Synthetic read-only routing test','goal':'Uppercase rendering',
              'diagnosis':diagnosis,'verification':[], 'source_files':{'render.py':str(source)},
              'frozen_files':{str(source):file_hash(source)},'edit_files':['render.py'],
              'proposal_evidence':[source_evidence('render.py',source.read_bytes().decode(),['render'])],
              'saved_response':json.dumps(saved)}
        p=root/'plan.json';p.write_text(json.dumps(plan));p.with_suffix('.sha256').write_text(file_hash(p))
        return p,saved

    def model(self, saved, blocked=False):
        class Model:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1;data=json.loads(messages[1]['content']);fields=kwargs['schema']['properties']
                if 'outcome' in fields:
                    row=next(x for x in data['observations'] if 'text' in x)
                    value={'outcome':'supported','evidence_ids':[row['fact_id']],
                           'assessment':'Return lacks uppercasing','next_step':'Uppercase result','checks':[]}
                elif 'edits' in fields:
                    if blocked:return Reply(json.dumps(saved),10)
                    row=data['readonly_diagnostic_evidence'][0]
                    value={'summary':'Propose uppercase','edits':[{'path':'render.py','old':'return str(value)',
                        'new':'return str(value).upper()'}],'diagnostic_answer':{
                        'question':data['diagnostic_check']['next_check'],'status':'source_answer',
                        'answer':'The return expression lacks uppercasing; uppercase the result',
                        'hypothesis_update':'supported','missing_evidence':'',
                        'citations':[{'path':row['path'],'sha256':row['sha256'],'quote':'return str(value)'}]}}
                else:value={'checks':[{'path':'render.py','start_line':1,'end_line':2}]}
                return Reply(json.dumps(value),10)
        return Model()

    def test_replays_saved_unknown_then_live_reads_and_holds_valid_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p,saved=self.prepare(root);model=self.model(saved)
            report=execute(p,root/'out',model=model)
            self.assertEqual(report['status'],'proposal_validated_edits_held')
            self.assertEqual(model.calls,3);self.assertTrue(report['workspace_unchanged'])
            self.assertEqual(report['budget']['model_calls'],4)
            self.assertEqual(report['budget']['tokens'],30)
            self.assertEqual(report['acceptance'],'not_executed')
            self.assertEqual(execute(p,root/'out',model=model),report);self.assertEqual(model.calls,3)
            self.assertEqual(len((root/'out/model-transcript.jsonl').read_text().splitlines()),7)

    def test_second_unknown_is_preserved_blocker_not_repair_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p,saved=self.prepare(root)
            report=execute(p,root/'out',model=self.model(saved,True))
            self.assertEqual(report['status'],'evidence_blocked');self.assertTrue(report['workspace_unchanged'])
            self.assertIn('remains insufficient',report['reason'])

    def test_changed_source_blocks_before_any_live_call(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p,saved=self.prepare(root);model=self.model(saved)
            (root/'source.py').write_text('changed')
            with self.assertRaisesRegex(ValueError,'Frozen input changed'):
                execute(p,root/'out',model=model)
            self.assertEqual(model.calls,0)
