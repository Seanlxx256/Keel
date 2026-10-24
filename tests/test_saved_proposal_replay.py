import json
import tempfile
import unittest
from pathlib import Path
from examples.replay_saved_proposal import execute
from keel.evaluation_protocol import file_hash
from keel.models import Reply
from keel.proposals import proposal_request, source_evidence


class SavedProposalReplayTests(unittest.TestCase):
    def fixture(self, root):
        source=root/'original.py'
        source.write_bytes(b'def left():\n    return 1\n\ndef right():\n    return 1\n')
        evidence=[source_evidence('app.py',source.read_text(),['return'])]
        messages,schema,_=proposal_request('Change right only',['app.py'],evidence,{'max_context_bytes':131072})
        request=root/'request.json';request.write_text(json.dumps({'args':[messages],'kwargs':{'schema':schema}}))
        rejected=root/'rejected.json';rejected.write_text(json.dumps({'summary':'change','edits':[{'path':'app.py','old':'    return 1','new':'    return 2'}]}))
        model=root/'model.json';model.write_text('{}')
        plan={'request':str(request),'rejected_response':str(rejected),'model_config':str(model),'source_files':{'app.py':str(source)},'output':str(root/'result')}
        plan['input_hashes']={str(p):file_hash(p) for p in (source,request,rejected,model)}
        path=root/'plan.json';path.write_text(json.dumps(plan));path.with_suffix('.sha256').write_text(file_hash(path))
        return path

    def test_exact_saved_request_gets_actionable_feedback_and_one_validated_correction(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=self.fixture(root)
            class Model:
                calls=0
                def complete_json(inner,messages,**kwargs):
                    inner.calls+=1
                    self.assertIn('column',json.loads(messages[1]['content'])['goal'])
                    self.assertLessEqual(kwargs['timeout'],60)
                    return Reply(json.dumps({'summary':'change right','edits':[{'path':'app.py','old':'def right():\n    return 1','new':'def right():\n    return 2'}]}),100)
            model=Model();result=execute(path,model=model)
            self.assertEqual(result['status'],'proposal_validated')
            self.assertEqual(model.calls,1)
            self.assertEqual(result['new_provider_calls'],1)
            self.assertEqual(result['changed_files'],['app.py'])
            self.assertIn('def right():\n    return 1',(root/'original.py').read_text())
            with self.assertRaisesRegex(ValueError,'exists'):
                execute(path,model=model)

    def test_invalid_correction_is_preserved_without_automatic_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=self.fixture(root)
            class Model:
                def complete_json(inner,*args,**kwargs):
                    return Reply((root/'rejected.json').read_text(),100)
            result=execute(path,model=Model())
            self.assertEqual(result['status'],'incomplete')
            self.assertEqual(result['new_provider_calls'],1)
            self.assertEqual(result['error_type'],'InvalidProposal')
            self.assertTrue((root/'result/response.json').is_file())
            self.assertEqual((root/'result/source/app.py').read_text(),(root/'original.py').read_text())

    def test_input_drift_prevents_provider_call(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=self.fixture(root)
            (root/'original.py').write_text('changed')
            with self.assertRaisesRegex(ValueError,'changed'):
                execute(path,model=object())
            self.assertFalse((root/'result').exists())
