import json
from pathlib import Path
import tempfile
import unittest

from examples.run_frozen_model_review import execute
from keel.evaluation_protocol import file_hash
from keel.models import Reply


class FrozenReviewTests(unittest.TestCase):
    def test_completion_rejection_preserves_partial_content_and_output_setting(self):
        from keel.core import ModelCompletionError
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,_=self.prepare(root);plan=json.loads(path.read_text())
            plan['requests']=plan['requests'][:1];plan['requests'][0]['max_output']=2048
            path.write_text(json.dumps(plan));path.with_suffix('.sha256').write_text(file_hash(path))
            class Model:
                def complete_json(self,*args,**kwargs):
                    self.maximum=kwargs['max_output']
                    raise ModelCompletionError('Incomplete completion',tokens=20,
                        diagnostics={'finish_reason':'length'},content='{"partial":')
            model=Model()
            with self.assertRaises(ModelCompletionError):execute(path,root/'out',model=model)
            record=json.loads((root/'out/summary.json').read_text())
            self.assertEqual(model.maximum,2048)
            self.assertEqual(record['completion_diagnostics']['finish_reason'],'length')
            self.assertEqual(record['rejected_response_content'],'{"partial":')
            self.assertEqual(record['budget']['tokens'],20)

    def diagnostic_plan(self, root):
        from keel.proposals import proposal_request, source_evidence
        source=root/'render.py';source.write_bytes(b'def render(value):\n    return str(value)\n')
        evidence=[source_evidence('render.py',source.read_bytes().decode(),['render'])]
        check={'next_check':'What output was observed during isolated execution?', 'hypothesis':'Unknown output'}
        messages,schema,_=proposal_request('Investigate',['render.py'],evidence,{},diagnostic_check=check)
        plan={'response_contract':'diagnostic_answer','frozen_files':{str(source):file_hash(source)},
              'scope':'Answer provenance only; no patch execution',
              'requests':[{'arm':'execution','messages':messages,'schema':schema,
                           'source_files':{'render.py':str(source)}}]}
        path=root/'plan.json';path.write_text(json.dumps(plan));path.with_suffix('.sha256').write_text(file_hash(path))
        response={'summary':'Execution unavailable','edits':[], 'diagnostic_answer':{
            'question':check['next_check'],'status':'unknown','answer':'No execution output is supplied',
            'hypothesis_update':'undetermined','missing_evidence':'Actual isolated execution output','citations':[]}}
        return path,response,source

    def test_diagnostic_unknown_is_completed_review_not_task_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,response,source=self.diagnostic_plan(root);before=source.read_bytes()
            class Model:
                calls=0
                def complete_json(self,*args,**kwargs):
                    self.calls+=1;return Reply(json.dumps(response),10)
            model=Model();report=execute(path,root/'out',model=model)
            execute(path,root/'out',model=model)
            self.assertEqual(model.calls,1)
            self.assertEqual(report['records'][0]['diagnostic_assessment']['status'],'unknown')
            self.assertEqual(report['records'][0]['diagnostic_assessment']['check_execution'],'not_established')
            self.assertIn('not_performed',report['records'][0]['patch_validation'])
            self.assertEqual(before,source.read_bytes())
            self.assertIsNone(report['automatic_quality_score'])

    def test_diagnostic_unknown_cannot_smuggle_patch_and_failure_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,response,source=self.diagnostic_plan(root)
            response['edits']=[{'path':'render.py','old':'str(value)','new':'value'}]
            class Model:
                calls=0
                def complete_json(self,*args,**kwargs):
                    self.calls+=1;return Reply(json.dumps(response),10)
            model=Model();before=source.read_bytes()
            with self.assertRaisesRegex(ValueError,'edits='):
                execute(path,root/'out',model=model)
            with self.assertRaisesRegex(ValueError,'automatic retry'):
                execute(path,root/'out',model=model)
            self.assertEqual(model.calls,1);self.assertEqual(before,source.read_bytes())

    def test_changed_diagnostic_source_fails_before_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,_,source=self.diagnostic_plan(root);source.write_text('changed')
            with self.assertRaisesRegex(ValueError,'Frozen input changed'):
                execute(path,root/'out',model=object())

    def test_handoff_contract_reuses_existing_runner_and_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,_=self.prepare(root);plan=json.loads(path.read_text())
            data={'source_evidence':[{'evidence_id':'s0','path':'render.py','text':'def render'}],
                  'replacement_choices':['render.py'],'handoff':{'selected_edit_paths':['render.py']}}
            plan['response_contract']='diagnostic_handoff'
            plan['requests']=[{'arm':'target','messages':[{'role':'system','content':'review'},
                {'role':'user','content':json.dumps(data)}],'schema':{'type':'object'}}]
            path.write_text(json.dumps(plan));path.with_suffix('.sha256').write_text(file_hash(path))
            class Model:
                calls=0
                def complete_json(self,*args,**kwargs):
                    self.calls+=1
                    return Reply(json.dumps({'verdict':'aligned','reason':'inspect render','answer':'render is the observed target',
                        'citations':[{'evidence_id':'s0','quote':'def render'}],'replacement_files':[]}),10)
            model=Model();first=execute(path,root/'out',model=model);second=execute(path,root/'out',model=model)
            self.assertEqual(model.calls,1)
            self.assertEqual(first,second)
            self.assertEqual(first['records'][0]['response']['verdict'],'aligned')

    def test_single_followup_does_not_repeat_completed_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path, fields = self.prepare(root)
            plan = json.loads(path.read_text()); plan['requests'] = plan['requests'][1:]
            path.write_text(json.dumps(plan)); path.with_suffix('.sha256').write_text(file_hash(path))
            class Model:
                calls = 0
                def complete_json(self, *args, **kwargs):
                    self.calls += 1
                    value = {f: 'stop' if f == 'action' else 'unverified' for f in fields}
                    value['evidence'] = 'x'*1023
                    return Reply(json.dumps(value), 30)
            model = Model(); report = execute(path, root/'out', model=model)
            self.assertEqual(model.calls, 1)
            self.assertEqual(len(report['records']), 1)
            self.assertEqual(len(report['records'][0]['response']['evidence']), 1023)
            self.assertEqual(report['records'][0]['response_warnings'][0]['characters'], 1023)

    def prepare(self, root):
        fields = ['action', 'reason', 'hypothesis', 'evidence', 'next_check', 'previous_attempt_assessment']
        plan = {'frozen_files': {}, 'requests': [
            {'arm': arm, 'messages': [{'role': 'user', 'content': 'diagnose'}],
             'schema': {'required': fields}} for arm in ('summary', 'source')],
            'scope': 'fixture review only'}
        path = root/'plan.json'; path.write_text(json.dumps(plan))
        path.with_suffix('.sha256').write_text(file_hash(path))
        return path, fields

    def test_completed_pair_reuses_receipts_without_new_paid_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan, fields = self.prepare(root)
            class Model:
                calls = 0
                def complete_json(self, *args, **kwargs):
                    self.calls += 1
                    return Reply(json.dumps({f: 'stop' if f == 'action' else 'unverified' for f in fields}), 30)
            model = Model()
            report = execute(plan, root/'out', model=model)
            self.assertEqual(model.calls, 2)
            self.assertIsNone(report['automatic_quality_score'])
            execute(plan, root/'out', model=model)
            self.assertEqual(model.calls, 2)
            (root/'out/summary.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'receipt mismatch'):
                execute(plan, root/'out', model=model)
            self.assertEqual(model.calls, 2)

    def test_interrupted_or_invalid_response_is_not_automatically_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan, _ = self.prepare(root)
            class Model:
                calls = 0
                def complete_json(self, *args, **kwargs):
                    self.calls += 1
                    return Reply('{}', 10)
            model = Model()
            with self.assertRaisesRegex(ValueError, 'Invalid Critic'):
                execute(plan, root/'out', model=model)
            with self.assertRaisesRegex(ValueError, 'automatic retry disabled'):
                execute(plan, root/'out', model=model)
            self.assertEqual(model.calls, 1)
            record = json.loads((root/'out/summary.json').read_text())
            self.assertEqual(record['raw_response'], '{}')
            self.assertEqual(record['budget']['tokens'], 10)
            self.assertIn('expected exactly', record['validation_error'])


if __name__ == '__main__':
    unittest.main()
