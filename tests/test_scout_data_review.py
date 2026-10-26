import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from keel.scout_data_audit import audit
from keel.scout_data_review import inspect_selection,review
from tests.test_scout_data_audit import events,write


class ScoutDataReviewTests(unittest.TestCase):
    def request(self,field,selected,data):
        request,response=events()
        request['kwargs']['schema']['properties']={field:{'type':'array','minItems':0 if 'catalog_page' in data else 1,
            'maxItems':8,'items':{'type':'string'}}}
        request['kwargs']['schema']['required']=[field]
        request['args'][0][0]['content']=json.dumps(data)
        response['content']=json.dumps({field:selected})
        return request,response

    def test_symbol_line_must_be_exact_identifier_not_plausible_line(self):
        req,res=self.request('locations',['pkg/module.py:12'],{'goal':'fix',
            'structure':[{'path':'pkg/module.py','symbols':[[10,'function']]}]})
        result=inspect_selection(req,res,{})
        self.assertEqual(result['decision'],'exclude_current_contract')
        self.assertIn('identifier_not_displayed_in_input_catalog',result['violations'])

    def test_legacy_catalog_test_path_is_rejected_by_current_shared_write_policy(self):
        req,res=self.request('files',['testing/test_feature.py'],{'paths':['testing/test_feature.py']})
        result=inspect_selection(req,res,{})
        self.assertIn('current_protected_write_target',result['violations'])

    def test_page_carry_is_legal_and_empty_is_not_automatically_negative(self):
        req,res=self.request('files',['pkg/previous.py'],{'paths':['pkg/new.py'],
            'previous_selection':['pkg/previous.py'],'catalog_page':2})
        result=inspect_selection(req,res,{})
        self.assertEqual(result['violations'],[])
        self.assertEqual(result['stage'],'file_catalog_page')
        res['content']='{"files":[]}'
        result=inspect_selection(req,res,{})
        self.assertEqual(result['decision'],'needs_semantic_review')
        self.assertIn('historical_empty_page_semantics_unverified',result['notes'])

    def test_historical_context_is_quarantined_not_called_answer_leakage(self):
        req,res=self.request('files',['pkg/a.py'],{'paths':['pkg/a.py']})
        result=inspect_selection(req,res,{'continuation':True,'diagnostic_report_present':True})
        self.assertEqual(result['decision'],'hold_provenance_review')
        self.assertFalse(result['training_approved'])

    def test_feedback_inside_goal_requires_review_even_without_sidecar_flags(self):
        req,res=self.request('files',['pkg/a.py'],{'paths':['pkg/a.py'],
            'goal':'Issue\nObserved failed verification (untrusted data):\n{}'})
        result=inspect_selection(req,res,{})
        self.assertEqual(result['decision'],'hold_provenance_review')
        self.assertIn('embedded_verification_feedback_requires_source_version_review',result['notes'])

    def test_protected_symbol_is_not_approved_even_if_visible(self):
        req,res=self.request('locations',['tests/test_a.py:1'],{'structure':[
            {'path':'tests/test_a.py','symbols':[[1,'test_a']]}]})
        result=inspect_selection(req,res,{})
        self.assertIn('current_protected_write_target',result['violations'])

    def fixture(self,root):
        source=root/'input';path=source/'model-transcript.jsonl'
        req,res=self.request('files',['pkg/a.py'],{'paths':['pkg/a.py'],'goal':'PRIVATE_PROMPT'})
        write(path,[req,res]);audit([source],root/'audit')
        h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        row=json.loads((root/'audit/candidates.jsonl').read_text())
        queue={'source_report_sha256':h(root/'audit/report.json'),
            'source_candidates_sha256':h(root/'audit/candidates.jsonl'),
            'items':[{k:row[k] for k in ['transcript','transcript_sha256','request_line','response_line','kind']}]}
        queue['items'][0]['instance_id']=row['context']['instance_id']
        q=root/'queue.json';q.write_text(json.dumps(queue))
        return path,q

    def test_real_audit_queue_review_preserves_identity_and_never_exports_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,queue=self.fixture(root)
            result=review(root/'audit',queue,root/'review')
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['counts'],{'needs_semantic_review':1})
            self.assertEqual(result['training_approved'],0)
            self.assertNotIn('PRIVATE_PROMPT',(root/'review/review.json').read_text())
            self.assertEqual(result['inputs'][str(path)],hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):review(root/'audit',queue,root/'review')

    def test_forged_queue_item_and_source_mutation_cannot_be_approved(self):
        for mode in ('queue','source'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);path,queue=self.fixture(root)
                if mode=='queue':
                    q=json.loads(queue.read_text());q['items'][0]['instance_id']='foreign__task-1';queue.write_text(json.dumps(q))
                    with self.assertRaisesRegex(ValueError,'provenance'):review(root/'audit',queue,root/'review')
                else:
                    with path.open('a') as stream:stream.write('{}\n')
                    result=review(root/'audit',queue,root/'review')
                    self.assertEqual(result['status'],'incomplete')
                    self.assertEqual(result['training_approved'],0)

    def test_absolute_and_parent_paths_are_not_valid_training_targets(self):
        for target in ('../outside.py','C:/outside.py','/outside.py'):
            req,res=self.request('files',[target],{'paths':[target]})
            self.assertIn('unsafe_relative_path',inspect_selection(req,res,{})['violations'])


if __name__=='__main__':unittest.main()
