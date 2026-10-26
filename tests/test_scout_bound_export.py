import json
from pathlib import Path
import tempfile
import unittest

from keel.scout_bound_export import export_bound
from keel.scout_collection import collect
from keel.scout_sft import PROMPT_VERSION
from keel.scout_data_audit import _digest
from keel.scout_tokenizer import file_hash
from tests import test_scout_collection
from tests.test_scout_adapter_eval import example


class ScoutBoundExportTests(unittest.TestCase):
    def fixture(self,root):
        helper=test_scout_collection.ScoutCollectionTests()
        try:plan,path,prepared=helper.plan_fixture(root)
        finally:helper.doCleanups()
        collection=root/'collection';collect(path,prepared,collection,model=test_scout_collection.FakeTeacher())
        base=root/'base';base.mkdir();ex=example();data=base/'development.jsonl';data.write_text(json.dumps(ex)+'\n')
        sample={'sample_id':'old','instance_id':'old__old-9','kind':'files','example_sha256':'old-example',
            'prompt_sha256':_digest(ex['prompt']),'completion_sha256':_digest(ex['completion'])}
        (base/'export.json').write_text(json.dumps({'status':'exported_development_only','prompt_version':PROMPT_VERSION,
            'inputs':{},'samples':[sample],'sample_count':1,'dataset_sha256':file_hash(data)}))
        review=root/'review.json';self.make_review(collection,review)
        return base,collection,review,Path(plan['reservation'])

    def make_review(self,collection,path,*,hold_symbol=False):
        run_path=collection/'collection.json';run=json.loads(run_path.read_text());task=run['tasks'][0]
        transcript=collection/task['instance_id']/'capture/model-transcript.jsonl';identity=file_hash(transcript)
        task['evidence'][str(transcript.resolve())]=identity;run_path.write_text(json.dumps(run))
        items=[];req=None
        for i,line in enumerate(transcript.read_text().splitlines(),1):
            event=json.loads(line)
            if event['event']=='request':req=(i,event)
            elif event['event']=='response':
                symbol='locations' in json.loads(event['content']);decision='hold_symbol_relevance_review' if hold_symbol and symbol else 'approved_development_smoke'
                items.append({'sample_id':_digest([identity,req[0],i]),'instance_id':task['instance_id'],
                    'transcript':str(transcript.resolve()),'transcript_sha256':identity,'request_line':req[0],'response_line':i,
                    'source_binding':event['source_binding'],'decision':decision,'reviewer':'unit_fixture',
                    'rationale':'Fixture, not real label approval','training_use':'development_smoke_only',
                    'independent_evaluation_eligible':False,'raw_target_modified':False,'original_goal_matches':True})
        path.write_text(json.dumps({'status':'reviewed_pending_export','inputs':{str(run_path.resolve()):file_hash(run_path),
            str(transcript.resolve()):identity},'items':items}))

    def test_append_preserves_base_bytes_original_responses_and_no_git_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base,collection,review,reservation=self.fixture(root);before=(base/'development.jsonl').read_bytes()
            result=export_bound(base,collection,review,reservation,root/'export')
            self.assertEqual(result['status'],'exported_development_only');self.assertEqual(result['sample_count'],3)
            self.assertEqual((base/'development.jsonl').read_bytes(),before)
            self.assertTrue((root/'export/development.jsonl').read_bytes().startswith(before))
            exported=[json.loads(x) for x in (root/'export/development.jsonl').read_text().splitlines()]
            transcript=next(collection.glob('*/capture/model-transcript.jsonl'))
            responses=[json.loads(x)['content'] for x in transcript.read_text().splitlines() if json.loads(x)['event']=='response']
            self.assertEqual([r['completion'][0]['content'] for r in exported[1:]],responses)
            self.assertEqual(result['model_calls'],0);self.assertEqual(result['weight_updates'],0)

    def test_held_record_is_not_rewritten_or_admitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base,collection,review,reservation=self.fixture(root)
            self.make_review(collection,review,hold_symbol=True)
            result=export_bound(base,collection,review,reservation,root/'export')
            self.assertEqual(result['sample_count'],2)
            self.assertEqual(result['not_exported'][0]['decision'],'hold_symbol_relevance_review')

    def test_changed_source_and_reserved_repository_reject_export(self):
        for corrupt_source in (True,False):
            with self.subTest(source=corrupt_source),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);base,collection,review,reservation=self.fixture(root)
                if corrupt_source:next(collection.glob('*/capture/objects/*')).write_bytes(b'changed')
                else:reservation.write_text(json.dumps({'assignments':{'tasks':{'demo__demo-99':{'partition':'transfer_review'}}}}))
                with self.assertRaises(ValueError):export_bound(base,collection,review,reservation,root/'bad')
                self.assertEqual(json.loads((root/'bad/export.json').read_text())['status'],'incomplete')
                self.assertFalse((root/'bad/development.jsonl').exists())

    def test_page_action_cannot_be_promoted_by_setting_approval_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base,collection,review,reservation=self.fixture(root)
            transcript=next(collection.glob('*/capture/model-transcript.jsonl'));events=[json.loads(x) for x in transcript.read_text().splitlines()]
            payload=json.loads(events[0]['args'][0][-1]['content']);payload['catalog_page']=1
            events[0]['args'][0][-1]['content']=json.dumps(payload)
            transcript.write_text(''.join(json.dumps(x)+'\n' for x in events));self.make_review(collection,review)
            with self.assertRaisesRegex(ValueError,'Paged or augmented'):export_bound(base,collection,review,reservation,root/'bad')
