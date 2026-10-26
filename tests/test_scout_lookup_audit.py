import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from keel.scout_candidate_ids import lookup_example
from keel.scout_lookup_audit import canonical_candidate_ids, assess_output, audit
from keel.scout_tokenizer import file_hash
from tests.test_scout_candidate_ids import fixture


class ScoutLookupAuditTests(unittest.TestCase):
    def setUp(self):
        self.mapping=['pkg/a.py:10','pkg/a.py:30','pkg/b.py:20']
        self.spec={'minItems':1,'maxItems':8}

    def test_format_recovery_is_target_independent_and_does_not_select_answers(self):
        text='```json\n{"candidate_ids":["1"]}\n```'
        canonical,changes=canonical_candidate_ids(text,self.mapping,self.spec)
        self.assertEqual(json.loads(canonical),{'candidate_ids':[1]})
        self.assertEqual(changes,['single_json_fence','decimal_string_to_integer'])
        right=assess_output(text,self.mapping,self.spec,1,'eos')
        wrong=assess_output(text,self.mapping,self.spec,2,'eos')
        self.assertEqual(right['normalized_output'],wrong['normalized_output'])
        self.assertFalse(right['strict_exact']);self.assertTrue(right['normalized_exact'])
        self.assertEqual(right['category'],'format_only');self.assertFalse(right['training_allowed'])
        self.assertEqual(wrong['category'],'wrong_candidate')

    def test_recovery_rejects_ambiguous_types_unknown_ids_duplicates_and_prose(self):
        for text in ('0','[1]','{"candidate_ids":[true]}','{"candidate_ids":[1.0]}',
                     '{"candidate_ids":["01"]}','{"candidate_ids":["+1"]}','{"candidate_ids":[" 1"]}',
                     '{"candidate_ids":["-1"]}','{"candidate_ids":["1.0"]}','{"candidate_ids":["3"]}',
                     '{"candidate_ids":["1",1]}','{"candidate_ids":["1"],"note":"ok"}',
                     '{"candidate_ids":["0"],"candidate_ids":["1"]}',
                     'Advice: ```json\n{"candidate_ids":["1"]}\n```','{"candidate_ids":["1"]'):
            with self.subTest(text=text),self.assertRaises(ValueError):canonical_candidate_ids(text,self.mapping,self.spec)

    def test_valid_wrong_or_overcomplete_selection_does_not_become_success(self):
        result=assess_output('{"candidate_ids":["0","1"]}',self.mapping,self.spec,1,'eos')
        self.assertTrue(result['normalized_valid']);self.assertFalse(result['normalized_exact'])
        self.assertEqual(result['category'],'over_selection')
        with self.assertRaises(ValueError):canonical_candidate_ids('{"candidate_ids":[0,1]}',self.mapping,{'minItems':1,'maxItems':1})
        incomplete=assess_output('{"candidate_ids":[0,',self.mapping,self.spec,1,'token_limit')
        self.assertEqual(incomplete['category'],'incomplete_generation')
        self.assertFalse(incomplete['normalized_valid'])

    def prepare(self,root):
        sample=fixture();sample['prompt'][0]['content']=sample['prompt'][0]['content'].replace('Select 1..8 definition locations.',
            'Select 1..8 definition locations from the supplied structure for repair.')
        data=root/'development.jsonl';data.write_text(json.dumps(sample)+'\n')
        export=root/'export.json';export.write_text(json.dumps({'dataset_sha256':file_hash(data)}))
        actual,mapping,_,_,meta=lookup_example(sample)
        rows=[]
        for arm,text in [('base','{"candidate_ids":["1"]}'),('adapter','{"candidate_ids":["0","1"]}')]:
            rows.append({'arm':arm,'sample':0,'output':text,'finish_reason':'eos','candidate_id_valid':False,
                'score':{'teacher_selection_equal':False},'lookup_control':meta,
                'candidate_mapping_sha256':hashlib.sha256(json.dumps(mapping).encode()).hexdigest(),
                'prompt_sha256':hashlib.sha256(json.dumps(actual['prompt'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()})
        source=root/'source.json';source.write_text(json.dumps({'status':'completed','task_control':'known_name_lookup',
            'cohort_file':'development.jsonl','dataset_sha256':file_hash(data),'rows':rows}))
        plan=root/'plan.json';plan.write_text(json.dumps({'inputs':{str(p.resolve()):file_hash(p) for p in (data,export,source)},
            'reports':[{'report':str(source),'dataset':str(root)}]}))
        return plan,source

    def test_replay_preserves_paid_outputs_and_uses_rebuilt_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan,source=self.prepare(root);before=source.read_bytes()
            result=audit(plan,root/'audit')
            self.assertEqual(source.read_bytes(),before);self.assertEqual(result['model_calls'],0)
            self.assertTrue(result['primary_scores_unchanged']);self.assertFalse(result['training_allowed'])
            summary=result['reports'][0]['summary']
            self.assertEqual(summary['base']['normalized_exact'],1)
            self.assertEqual(summary['adapter']['normalized_exact'],0)
            # Even a hash-bound report cannot redefine the deterministic answer.
            value=json.loads(source.read_text());value['rows'][0]['lookup_control']['expected_id']=0
            source.write_text(json.dumps(value));p=json.loads(plan.read_text());p['inputs'][str(source.resolve())]=file_hash(source)
            plan.write_text(json.dumps(p))
            with self.assertRaisesRegex(ValueError,'truth/query drift'):audit(plan,root/'bad')
            self.assertEqual(json.loads((root/'bad/report.json').read_text())['status'],'incomplete')

    def test_replay_rejects_incomplete_cohort_and_changed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan,source=self.prepare(root)
            source.write_text('{}')
            with self.assertRaisesRegex(ValueError,'input changed'):audit(plan,root/'drift')
            plan,source=self.prepare(root);value=json.loads(source.read_text());value['rows'].pop();source.write_text(json.dumps(value))
            p=json.loads(plan.read_text());p['inputs'][str(source.resolve())]=file_hash(source);plan.write_text(json.dumps(p))
            with self.assertRaisesRegex(ValueError,'complete symbol cohorts'):audit(plan,root/'partial')
