import copy
import json
import unittest
from keel.scout_candidate_ids import numbered_prompt,numbered_example,lookup_example,decode_ids,compare_reports,single_json_fence,MARKER


def fixture():
    system='Select 1..8 definition locations. Each symbols entry is [definition_line, name]. Return locations only as path:line, combining a displayed file path and its displayed definition line.'
    schema={'properties':{'locations':{'minItems':1,'maxItems':8}}}
    return {'prompt':[{'role':'system','content':system+MARKER+json.dumps(schema)},
        {'role':'user','content':json.dumps({'goal':'Issue traceback line 987 is untrusted data',
            'structure':[{'path':'pkg/a.py','symbols':[[10,'first'],[30,'second']],'definition_bytes':[40,50]},
                         {'path':'pkg/b.py','symbols':[[20,'third']]}]})}],
        'completion':[{'role':'assistant','content':'{"locations":["pkg/a.py:30"]}'}]}


class ScoutCandidateIdTests(unittest.TestCase):
    def test_permutations_preserve_candidates_metadata_and_logical_teacher(self):
        a=fixture(); original=copy.deepcopy(a)
        reference,mapping,spec=numbered_example(a)
        for mode in ('reverse_ids','reverse_catalog'):
            transformed,other,other_spec=numbered_example(a,permutation=mode)
            self.assertEqual(other,list(reversed(mapping)))
            self.assertEqual(other_spec,spec)
            self.assertEqual(json.loads(decode_ids(transformed['completion'][0]['content'],other,spec)),
                             json.loads(a['completion'][0]['content']))
            payload=json.loads(transformed['prompt'][-1]['content'])
            if mode=='reverse_catalog':
                self.assertEqual(payload['structure'][-1]['definition_bytes'],[50,40])
                self.assertEqual(payload['structure'][-1]['symbols'][0][:2],[30,'second'])
            else:
                self.assertEqual(payload['structure'][0]['symbols'][0],[10,'first',2])
            b=copy.deepcopy(a);b['completion'][0]['content']='{"locations":["pkg/b.py:20"]}'
            self.assertEqual(numbered_example(b,permutation=mode)[0]['prompt'],transformed['prompt'])
        self.assertEqual(a,original)
        with self.assertRaisesRegex(ValueError,'permutation'):numbered_example(a,permutation='answer_first')

    def test_lookup_presentations_keep_every_candidate_and_same_answer(self):
        a=fixture();a['prompt'][0]['content']=a['prompt'][0]['content'].replace('Select 1..8 definition locations.',
            'Select 1..8 definition locations from the supplied structure for repair.')
        original=copy.deepcopy(a)
        reference,mapping,spec,scoring,meta=lookup_example(a)
        for mode in ('without_goal','flat'):
            actual,other,other_spec,other_scoring,info=lookup_example(a,presentation=mode)
            self.assertEqual(other,mapping);self.assertEqual(other_spec,spec)
            self.assertEqual(other_scoring,scoring);self.assertEqual(info['query'],meta['query'])
            self.assertEqual(actual['completion'],reference['completion'])
            payload=json.loads(actual['prompt'][-1]['content'])
            self.assertNotIn('goal',payload)
            if mode=='without_goal':
                expected=json.loads(reference['prompt'][-1]['content']);expected.pop('goal')
                self.assertEqual(payload,expected)
            else:
                self.assertEqual(payload['candidates'],[
                    {'candidate_id':0,'path':'pkg/a.py','name':'first'},
                    {'candidate_id':1,'path':'pkg/a.py','name':'second'},
                    {'candidate_id':2,'path':'pkg/b.py','name':'third'}])
                b=copy.deepcopy(a);b['completion'][0]['content']='{"locations":["unknown.py:999"]}'
                self.assertEqual(lookup_example(b,presentation=mode)[0],actual)
        self.assertEqual(a,original)
        with self.assertRaisesRegex(ValueError,'presentation'):lookup_example(a,presentation='filter_by_answer')

    def test_lookup_target_and_prompt_ignore_original_repair_teacher(self):
        a=fixture();a['prompt'][0]['content']=a['prompt'][0]['content'].replace('Select 1..8 definition locations.',
            'Select 1..8 definition locations from the supplied structure for repair.')
        b=copy.deepcopy(a);b['completion'][0]['content']='{"locations":["not/a/real/teacher.py:999"]}'
        x,mapping,spec,scoring,meta=lookup_example(a);y,_,_,_,other=lookup_example(b)
        self.assertEqual(x,y);self.assertEqual(meta,other)
        self.assertEqual(meta['expected_id'],1)
        self.assertEqual(json.loads(x['prompt'][-1]['content'])['goal'],json.loads(a['prompt'][-1]['content'])['goal'])
        self.assertEqual(json.loads(decode_ids(x['completion'][0]['content'],mapping,spec)),json.loads(scoring['completion'][0]['content']))
    def test_fence_diagnostic_only_removes_one_complete_wrapper(self):
        self.assertEqual(single_json_fence('```json\n{"candidate_ids":[0]}\n```'),'{"candidate_ids":[0]}')
        for text in ('Advice\n```json\n{}\n```','```json\n{}','```json\n{}\n```\n```json\n{}\n```'):
            self.assertEqual(single_json_fence(text),text)
    def test_comparison_rejects_changed_checkpoint_and_does_not_compare_nll(self):
        row={'sample':1,'score':{'json_valid':True,'contract_valid':True,'teacher_selection_equal':False},
            'finish_reason':'eos','candidate_id_valid':True}
        free={'status':'completed','dataset_sha256':'d','training_receipt_sha256':'t','checkpoint_step':24,'generation':{},
            'rows':[dict(row,arm=arm) for arm in ('base','adapter')]}
        numbered={**free,'representation':'candidate_ids','symbol_only':True}
        result=compare_reports(free,numbered)
        self.assertEqual(result['adapter']['candidate_ids']['contract_valid'],1)
        self.assertEqual(result['adapter']['candidate_ids']['teacher_selection_equal'],0)
        self.assertNotIn('teacher_nll',result['adapter']['candidate_ids'])
        with self.assertRaisesRegex(ValueError,'identity'):compare_reports(free,{**numbered,'checkpoint_step':6})
    def test_mapping_comes_only_from_catalog_and_original_input_is_unchanged(self):
        example=fixture();original=copy.deepcopy(example)
        prompt,mapping,spec=numbered_prompt(example['prompt'])
        self.assertEqual(example,original)
        self.assertEqual(mapping,['pkg/a.py:10','pkg/a.py:30','pkg/b.py:20'])
        payload=json.loads(prompt[-1]['content'])
        self.assertEqual(payload['goal'],json.loads(original['prompt'][-1]['content'])['goal'])
        self.assertEqual(payload['structure'][0]['definition_bytes'],[40,50])
        self.assertEqual(spec['items']['enum'],[0,1,2])

    def test_changing_reference_does_not_change_prompt_or_catalog(self):
        a=fixture();b=copy.deepcopy(a);b['completion'][0]['content']='{"locations":["pkg/b.py:20"]}'
        x,mapping,spec=numbered_example(a);y,_,_=numbered_example(b)
        self.assertEqual(x['prompt'],y['prompt'])
        self.assertNotEqual(x['completion'],y['completion'])
        self.assertEqual(json.loads(decode_ids('{"candidate_ids":[1]}',mapping,spec)),{'locations':['pkg/a.py:30']})

    def test_wrong_but_legal_candidate_remains_wrong_no_nearest_answer_projection(self):
        _,mapping,spec=numbered_prompt(fixture()['prompt'])
        self.assertEqual(json.loads(decode_ids('{"candidate_ids":[0]}',mapping,spec)),{'locations':['pkg/a.py:10']})
        for text in ('{"candidate_ids":[987]}','{"candidate_ids":[true]}','{"candidate_ids":["1"]}',
                     '{"candidate_ids":[1,1]}','{"candidate_ids":[]}','{"locations":["pkg/a.py:30"]}'):
            with self.assertRaises(ValueError):decode_ids(text,mapping,spec)
