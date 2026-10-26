import json
import unittest
import tempfile
from pathlib import Path
from keel.scout_adapter_eval import score,summarize,rescore,cached_baseline
from keel.scout_tokenizer import file_hash
from unittest.mock import patch


def example(field='files'):
    allowed=['pkg/core.py','pkg/other.py']
    data={'paths':allowed} if field=='files' else {'structure':[{'path':'pkg/core.py','symbols':[[10,'main'],[20,'other']]}]}
    schema={'type':'object','properties':{field:{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':8}},
        'required':[field],'additionalProperties':False}
    return {'prompt':[{'role':'system','content':'Required output schema (JSON):\n'+json.dumps(schema)},
        {'role':'user','content':json.dumps(data)}],
        'completion':[{'role':'assistant','content':json.dumps({field:['pkg/core.py' if field=='files' else 'pkg/core.py:10']})}]}


class ScoutAdapterEvalTests(unittest.TestCase):
    def test_transfer_identity_uses_sample_receipts_not_training_task_counts(self):
        from keel.scout_adapter_eval import transfer_task_ids
        self.assertEqual(transfer_task_ids({'samples':[{'instance_id':'repo-task'}]}),{'repo-task'})
        for meta in ({'tasks':['repo-task']},{'samples':[]},{'samples':[{}]},{'samples':[{'instance_id':None}]}):
            with self.assertRaises(ValueError):transfer_task_ids(meta)
    def test_lookup_only_cohort_cannot_be_used_as_repair_truth(self):
        from keel.scout_adapter_eval import validate_task_control
        validate_task_control({'allowed_task_control':'known_name_lookup'},True)
        with self.assertRaisesRegex(ValueError,'restricted'):validate_task_control({'allowed_task_control':'known_name_lookup'},False)
    def test_checkpoint_validation_uses_dataset_and_epochs_not_four_step_constant(self):
        from keel.scout_adapter_eval import evaluation_inputs
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();run=root/'run';(run/'training').mkdir(parents=True)
            (data/'export.json').write_text(json.dumps({'sample_count':6}))
            steps=[{'checkpoint_files':{'adapter':'hash'}} for _ in range(24)]
            training={'status':'passed','epochs':4,'steps':steps,'dataset_sha256':'data'}
            path=run/'training/training.json';path.write_text(json.dumps(training))
            (run/'report.json').write_text(json.dumps({'status':'passed','training_sha256':file_hash(path)}))
            with patch('keel.scout_adapter_eval.training_inputs',return_value=(root,{'identity':{'inputs':{'development.jsonl':'data'}}})),\
                 patch('keel.scout_adapter_eval.weight_hash',return_value='hash'):
                self.assertEqual(evaluation_inputs(data,root,run,6)[-1].name,'step-6')
                self.assertEqual(evaluation_inputs(data,root,run,24)[-1].name,'step-24')
                with self.assertRaisesRegex(ValueError,'outside'):evaluation_inputs(data,root,run,25)
                training.update(max_updates=20,expected_steps=20,steps=steps[:20])
                path.write_text(json.dumps(training))
                (run/'report.json').write_text(json.dumps({'status':'passed','training_sha256':file_hash(path)}))
                self.assertEqual(evaluation_inputs(data,root,run,20)[-1].name,'step-20')
                with self.assertRaisesRegex(ValueError,'outside'):evaluation_inputs(data,root,run,21)
                training['expected_steps']=24;path.write_text(json.dumps(training))
                with self.assertRaisesRegex(ValueError,'budget'):evaluation_inputs(data,root,run,20)
    def test_baseline_reuse_requires_same_data_config_and_training_receipt(self):
        source={'status':'completed','dataset_sha256':'data','training_receipt_sha256':'training',
            'generation':{'do_sample':False},'rows':[{'arm':'base','sample':0},{'arm':'adapter','sample':0}]}
        current={'dataset_sha256':'data','training_receipt_sha256':'training','generation':{'do_sample':False}}
        self.assertEqual(len(cached_baseline(source,current,1)),1)
        for key in ('dataset_sha256','training_receipt_sha256','generation'):
            with self.assertRaisesRegex(ValueError,'identity'):cached_baseline(source,{**current,key:'changed'},1)
        for key in ('representation','symbol_only','candidate_permutation','task_control','lookup_presentation'):
            with self.assertRaisesRegex(ValueError,'interface'):cached_baseline(source,{**current,key:'changed'},1)
        with self.assertRaisesRegex(ValueError,'incomplete'):cached_baseline(source,current,2)
        sparse={**source,'rows':[{'arm':'base','sample':i} for i in [1,3]]}
        self.assertEqual(len(cached_baseline(sparse,current,2,{1,3})),2)
        with self.assertRaisesRegex(ValueError,'incomplete'):cached_baseline(sparse,current,2,{0,1})

    def test_cached_id_prompt_is_reconstructed_before_reuse(self):
        import hashlib
        from keel.scout_adapter_eval import validate_cached_prompts
        from keel.scout_candidate_ids import numbered_example
        from tests.test_scout_candidate_ids import fixture
        sample=fixture();actual=numbered_example(sample)[0]
        h=hashlib.sha256(json.dumps(actual['prompt'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        rows=[{'sample':0,'prompt_sha256':h}]
        validate_cached_prompts(rows,[sample],{0},'candidate_ids',False,'original','original')
        with self.assertRaisesRegex(ValueError,'prompt changed'):
            validate_cached_prompts(rows,[sample],{0},'candidate_ids',False,'original','reverse_ids')
    def test_correct_catalog_selection_is_not_semantic_optimum_claim(self):
        result=score(example(),'{"files":["pkg/core.py"]}')
        self.assertTrue(result['contract_valid']);self.assertTrue(result['teacher_selection_equal'])
        self.assertIn('not unique',result['scope'])

    def test_wrong_displayed_selection_is_valid_but_not_teacher_match(self):
        result=score(example(),'{"files":["pkg/other.py"]}')
        self.assertTrue(result['contract_valid']);self.assertFalse(result['teacher_selection_equal'])
        self.assertEqual(result['teacher_recall'],0)

    def test_invalid_json_or_unknown_symbols_not_silently_repaired(self):
        for text in ('```json\n{"locations":["pkg/core.py:10"]}\n```','{"locations":["pkg/core.py:11"]}'):
            result=score(example('locations'),text)
            self.assertFalse(result['contract_valid']);self.assertFalse(result['teacher_selection_equal'])

    def test_duplicates_and_extra_keys_do_not_gain_exact_match(self):
        for text in ('{"files":["pkg/core.py","pkg/core.py"]}','{"files":["pkg/core.py"],"reason":"yes"}'):
            self.assertFalse(score(example(),text)['teacher_selection_equal'])

    def test_json_array_is_valid_json_but_invalid_selection_object(self):
        result=score(example(),'["pkg/core.py"]')
        self.assertTrue(result['json_valid']);self.assertFalse(result['json_object'])
        self.assertFalse(result['contract_valid'])

    def test_nll_is_weighted_by_target_tokens_and_caps_reported_separately(self):
        rows=[{'arm':'base','score':{'json_valid':True,'contract_valid':True,'teacher_selection_equal':True},
            'labelled_tokens':n,'teacher_nll':loss,'finish_reason':reason} for n,loss,reason in [(1,4,'eos'),(3,2,'token_limit')]]
        summary=summarize(rows)
        self.assertEqual(summary['base']['teacher_token_nll'],2.5)
        self.assertEqual(summary['base']['censored_generations'],1)
        self.assertIsNone(summary['adapter']['teacher_token_nll'])

    def test_rescore_reuses_raw_outputs_and_preserves_original_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();source=root/'source';source.mkdir()
            (data/'development.jsonl').write_text(json.dumps(example())+'\n')
            rows=[{'arm':arm,'sample':0,'output':'["pkg/core.py"]','labelled_tokens':1,
                'teacher_nll':1.0,'finish_reason':'eos','score':{'json_valid':False}} for arm in ('base','adapter')]
            (source/'report.json').write_text(json.dumps({'status':'completed','dataset_sha256':file_hash(data/'development.jsonl'),'rows':rows}))
            original=(source/'report.json').read_bytes()
            result=rescore(data,source,root/'rescore')
            self.assertEqual((source/'report.json').read_bytes(),original)
            self.assertEqual(result['summary']['base']['json_valid'],1)
            self.assertEqual(result['summary']['base']['contract_valid'],0)
            self.assertEqual(result['rescore']['new_generation_calls'],0)
