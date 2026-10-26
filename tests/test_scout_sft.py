import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from keel.scout_data_audit import audit
from keel.scout_data_review import review
from keel.scout_sft import training_prompt,completion_labels,export_development,_base_source
from tests.test_scout_data_audit import events,write


class ScoutSftTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'input';path=source/'model-transcript.jsonl';rows=events()
        rows[0]['args'][0][0]['content']=json.dumps({'goal':'issue','paths':['module.py','other.py']})
        write(path,[*rows,{'event':'observation','content':'FUTURE_OBSERVATION_NOT_INPUT'}])
        audit([source],root/'audit')
        h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        row=json.loads((root/'audit/candidates.jsonl').read_text())
        q={'source_report_sha256':h(root/'audit/report.json'),'source_candidates_sha256':h(root/'audit/candidates.jsonl'),
           'items':[{k:row[k] for k in ['transcript','transcript_sha256','request_line','response_line','kind']}]}
        q['items'][0]['instance_id']=None;queue=root/'queue.json';queue.write_text(json.dumps(q))
        result=review(root/'audit',queue,root/'review');item=result['items'][0]
        receipt=source/'input-receipt.json';receipt.write_text(json.dumps({'goal':'issue'}))
        evidence={'repo':str(root),'base_commit':'a'*40,'path':'module.py','source_sha256':'f'*64,
                  'receipt_sha256':h(receipt)}
        e=root/'review/developer-source-evidence.json';e.write_text(json.dumps({'items':[evidence]}))
        approval={'source_review_sha256':h(root/'review/review.json'),'source_evidence_sha256':h(e),
            'items':[{'sample_id':item['sample_id'],'instance_id':None,'example_sha256':item['example_sha256'],
                'decision':'approved_development_smoke','training_use':'development_smoke_only',
                'independent_evaluation_eligible':False,'raw_target_modified':False,'reviewer':'fixture_reviewer',
                'rationale':'Unit fixture, not real semantic review','input_goal_matches_original_receipt':True,
                'input_receipt':{'path':str(receipt),'sha256':h(receipt)},'source_evidence':[evidence]}]}
        a=root/'review/developer-assessments.json';a.write_text(json.dumps(approval))
        return path,a,rows

    def test_prompt_schema_is_visible_without_modifying_original_messages(self):
        messages=[{'role':'user','content':'issue'}];original=copy.deepcopy(messages)
        prompt=training_prompt(messages,{'enum':['module.py']})
        self.assertEqual(messages,original)
        self.assertEqual(prompt[0]['role'],'system')
        self.assertIn('module.py',prompt[0]['content'])

    def test_completion_mask_ignores_prompt_and_preserves_unshifted_target_ids(self):
        self.assertEqual(completion_labels([1,2,3,4,0],[0,0,1,1,0]),[-100,-100,3,4,-100])
        for ids,mask in [([1],[0]),([1],[1]),([1,2],[0]),([1,2],[0,.5]),([1,2],[0,1.0]),
                         ([1,2,3,4],[0,1,0,1])]:
            with self.subTest(ids=ids,mask=mask),self.assertRaises(ValueError):completion_labels(ids,mask)

    def test_review_to_real_prompt_completion_export_excludes_future_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,approval,rows=self.fixture(root)
            result=export_development(root/'review',root/'out',source_reader=lambda e,r:e['source_sha256'])
            self.assertEqual(result['status'],'exported_development_only',result)
            data=json.loads((root/'out/development.jsonl').read_text())
            self.assertEqual(data['completion'],[{'role':'assistant','content':rows[1]['content']}])
            self.assertIn('Required output schema',data['prompt'][0]['content'])
            self.assertNotIn('FUTURE_OBSERVATION_NOT_INPUT',json.dumps(data))
            self.assertEqual(result['sample_count'],1);self.assertEqual(result['weight_updates'],0)
            fixture=json.loads((root/'out/mask-fixture.json').read_text())
            self.assertFalse(fixture['real_model_tokenizer_verified'])
            with self.assertRaises(FileExistsError):export_development(root/'review',root/'out')

    def test_no_approval_scope_escalation_or_duplicate_creates_training_dataset(self):
        for mode in ('none','scope','heldout','duplicate','target_modified'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);path,a,rows=self.fixture(root);value=json.loads(a.read_text())
                if mode=='none':value['items'][0]['decision']='needs_semantic_review'
                if mode=='scope':value['items'][0]['training_use']='production_training'
                if mode=='heldout':value['items'][0]['independent_evaluation_eligible']=True
                if mode=='duplicate':value['items'].append(value['items'][0])
                if mode=='target_modified':value['items'][0]['raw_target_modified']=True
                a.write_text(json.dumps(value))
                result=export_development(root/'review',root/'out',source_reader=lambda e,r:e['source_sha256'])
                self.assertEqual(result['status'],'incomplete')
                self.assertFalse((root/'out/development.jsonl').exists())

    def test_source_or_semantic_evidence_change_stops_export(self):
        for mode in ('transcript','base_source'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);path,a,rows=self.fixture(root)
                if mode=='transcript':
                    with path.open('a') as f:f.write('{}\n')
                result=export_development(root/'review',root/'out',source_reader=lambda e,r:'wrong')
                self.assertEqual(result['status'],'incomplete')
                self.assertFalse((root/'out/development.jsonl').exists())

    @unittest.skipUnless(shutil.which('git'),'Git unavailable')
    def test_base_source_reader_uses_immutable_commit_not_changed_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            repo=Path(temp);command=['git','-c','safe.directory='+repo.as_posix(),'-C',str(repo)]
            def git(*args):return subprocess.run([*command,*args],capture_output=True,check=True,timeout=10).stdout
            git('init');raw=b'def original():\n    return 1\n';(repo/'module.py').write_bytes(raw)
            git('add','module.py');git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture')
            commit=git('rev-parse','HEAD').decode().strip();(repo/'module.py').write_text('changed worktree')
            evidence={'repo':str(repo),'base_commit':commit,'path':'module.py','source_sha256':hashlib.sha256(raw).hexdigest()}
            self.assertEqual(_base_source(evidence,lambda:20),evidence['source_sha256'])


if __name__=='__main__':unittest.main()
