import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from keel.scout_candidate_scoring import json_value_spans,encode_candidate_prompt,candidate_membership,balanced_membership_loss,select_candidates,ranking_metrics
from keel.scout_candidate_ids import numbered_example
from tests.test_scout_candidate_ids import fixture


class CharacterTokenizer:
    def apply_chat_template(self,messages,**kwargs):
        return ''.join(m['role']+'\n'+m['content']+'\n' for m in messages)+'assistant\n'
    def __call__(self,text,**kwargs):
        value={'input_ids':[ord(c) for c in text]}
        if kwargs.get('return_offsets_mapping'):value['offset_mapping']=[(i,i+1) for i in range(len(text))]
        return value


class CandidateScoringTests(unittest.TestCase):
    def test_checkpoint_representation_is_bound_across_all_receipts(self):
        import tempfile
        from keel.scout_adapter_eval import evaluation_inputs
        from keel.scout_tokenizer import file_hash
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir()
            (data/'export.json').write_text('{"sample_count":1}')
            run=root/'run';checkpoint=run/'training/step-1';checkpoint.mkdir(parents=True)
            policy='id_free_after'
            training={'objective':'candidate_scores','score_representation':policy,'status':'passed',
                'epochs':1,'dataset_sha256':'data','steps':[{'checkpoint_files':{},'score_representation':policy}]}
            parent={'status':'passed','identity':{'objective':'candidate_scores','score_representation':policy}}
            meta={'score_representation':policy}
            def save():
                path=run/'training/training.json';path.write_text(json.dumps(training))
                parent['training_sha256']=file_hash(path)
                (run/'report.json').write_text(json.dumps(parent))
                (checkpoint/'step.json').write_text(json.dumps(meta))
            with patch('keel.scout_adapter_eval.training_inputs',return_value=(root,{'identity':{'inputs':{'development.jsonl':'data'}}})):
                save();self.assertEqual(evaluation_inputs(data,root,run)[-1],checkpoint)
                for target in (training,training['steps'][0],meta):
                    target['score_representation']='numbered_end';save()
                    with self.assertRaisesRegex(ValueError,'representation drift'):evaluation_inputs(data,root,run)
                    target['score_representation']=policy

    def test_representation_policy_rejects_generation_and_unknown_values(self):
        from keel.scout_candidate_scoring import validate_score_representation,encode_score_input
        self.assertEqual(validate_score_representation('legacy','generation'),'legacy')
        for value,objective in [('id_free_after','generation'),('typo','candidate_scores')]:
            with self.assertRaises(ValueError):validate_score_representation(value,objective)
        sample=numbered_example(fixture())[0]
        self.assertEqual(encode_score_input(CharacterTokenizer(),sample['prompt']),
                         encode_candidate_prompt(CharacterTokenizer(),sample['prompt']))

    def test_evaluator_rejects_representation_override_before_gpu(self):
        from keel.scout_score_eval import evaluate_scores
        training={'objective':'candidate_scores','score_representation':'id_free_after'}
        with patch('keel.scout_score_eval.evaluation_inputs',return_value=(None,None,training,Path('step-1'))):
            with self.assertRaisesRegex(ValueError,'differs from training'):
                evaluate_scores('unused','unused','unused','unused',score_representation='numbered_end')

    def test_factorial_interface_removes_schema_in_all_variants(self):
        from keel.scout_candidate_scoring import encode_scoring_variant
        sample=numbered_example(fixture())[0]
        for input_mode in ('numbered','without_ids'):
            for readout in ('candidate_end','after_catalog'):
                value=encode_scoring_variant(CharacterTokenizer(),sample['prompt'],input_mode=input_mode,readout_mode=readout)
                text=''.join(chr(i) for i in value['input_ids'])
                self.assertNotIn('Required output schema',text)
                self.assertNotIn('"enum"',text)
                self.assertEqual(len(value['candidates']),len(json.loads(sample['prompt'][-1]['content'])['structure'][0]['symbols'])+
                                 sum(len(r['symbols']) for r in json.loads(sample['prompt'][-1]['content'])['structure'][1:]))

    def test_id_free_input_is_identical_after_id_only_permutation(self):
        a=numbered_example(fixture())[0]
        b=numbered_example(fixture(),permutation='reverse_ids')[0]
        for mode in ('candidate_end','after_catalog','after_catalog_grouped'):
            left=encode_candidate_prompt(CharacterTokenizer(),a['prompt'],input_mode='without_ids',readout_mode=mode)
            right=encode_candidate_prompt(CharacterTokenizer(),b['prompt'],input_mode='without_ids',readout_mode=mode)
            self.assertEqual(left['input_ids'],right['input_ids'])
            self.assertEqual([c['location'] for c in left['candidates']], [c['location'] for c in right['candidates']])
            self.assertNotEqual([c['candidate_id'] for c in left['candidates']], [c['candidate_id'] for c in right['candidates']])

    def test_after_catalog_readouts_follow_every_catalog_entry(self):
        sample=numbered_example(fixture())[0]
        features=encode_candidate_prompt(CharacterTokenizer(),sample['prompt'],readout_mode='after_catalog')
        text=''.join(chr(i) for i in features['input_ids'])
        payload_start=text.index('{',text.index('user\n'))
        _,spans=json_value_spans(text[payload_start:text.rindex('\nassistant\n')].rstrip())
        end=payload_start+spans[('structure',)][1]
        self.assertTrue(all(c['character_span'][0]>=end for c in features['candidates']))
        sample['completion'][0]['content']='CHANGED_TEACHER'
        self.assertEqual(features,encode_candidate_prompt(CharacterTokenizer(),sample['prompt'],readout_mode='after_catalog'))

    def test_grouped_readouts_preserve_every_candidate_without_repeating_path(self):
        sample=numbered_example(fixture())[0]
        for mode in ('numbered','without_ids'):
            features=encode_candidate_prompt(CharacterTokenizer(),sample['prompt'],input_mode=mode,readout_mode='after_catalog_grouped')
            text=''.join(chr(i) for i in features['input_ids'])
            payload_start=text.index('{',text.index('user\n'))
            payload,spans=json_value_spans(text[payload_start:text.rindex('\nassistant\n')].rstrip())
            self.assertEqual([{'path':r['path'],'symbols':r['symbols']} for r in payload['structure']],payload['scoring_readouts'])
            end=payload_start+spans[('structure',)][1]
            self.assertTrue(all(c['character_span'][0]>=end for c in features['candidates']))
            original=encode_candidate_prompt(CharacterTokenizer(),sample['prompt'])
            self.assertEqual([(c['location'],c['candidate_id']) for c in original['candidates']],
                             [(c['location'],c['candidate_id']) for c in features['candidates']])

    def test_score_evaluator_rejects_generation_or_missing_head_before_dispatch(self):
        from keel.scout_score_eval import evaluate_scores
        with patch('keel.scout_score_eval.evaluation_inputs',return_value=(None,None,{'objective':'generation'},Path('step-1'))):
            with self.assertRaisesRegex(ValueError,'checkpoint and head'):
                evaluate_scores('unused','unused','unused','unused')
        training={'objective':'candidate_scores','steps':[{'checkpoint_files':{}}]}
        with patch('keel.scout_score_eval.evaluation_inputs',return_value=(None,None,training,Path('step-1'))):
            with self.assertRaisesRegex(ValueError,'checkpoint and head'):
                evaluate_scores('unused','unused','unused','unused')
    def test_selection_uses_fixed_threshold_without_answer_count_or_fallback(self):
        candidates=[{'location':f'file.py:{i}','candidate_id':i} for i in range(12)]
        self.assertEqual(select_candidates(candidates,[0.1]*12),[])
        chosen=select_candidates(candidates,[0.9]*12)
        self.assertEqual(len(chosen),8)
        self.assertEqual(chosen,select_candidates(list(reversed(candidates)),[0.9]*12))
        for probabilities in ([float('nan')]*12,[1.1]*12,[]):
            with self.assertRaises(ValueError):select_candidates(candidates,probabilities)
        self.assertEqual(select_candidates(candidates,[0.1,0.8]+[0.1]*10)[0]['candidate_id'],1)

    def test_ranking_ties_do_not_get_oracle_ordering(self):
        self.assertEqual(ranking_metrics([0.5,0.5],[1,0])['teacher_average_precision'],0.5)
        self.assertEqual(ranking_metrics([0.9,0.1],[1,0])['teacher_average_precision'],1.)
        with self.assertRaises(ValueError):ranking_metrics([0.1],[0])
    def test_structural_spans_handle_escapes_repetition_and_reordering(self):
        payload={'goal':'read repeated name \\" unicode \u03bb','structure':[
            {'path':'pkg/"odd\\name.py','symbols':[[1,'repeat',0],[20,'repeat',1]]},
            {'path':'other.py','symbols':[[1,'repeat',2]]}]}
        text=json.dumps(payload,ensure_ascii=False);value,spans=json_value_spans(text)
        self.assertEqual(value,payload)
        for ri,row in enumerate(payload['structure']):
            for si,symbol in enumerate(row['symbols']):
                start,end=spans['structure',ri,'symbols',si]
                self.assertEqual(json.loads(text[start:end]),symbol)
        messages=[{'role':'system','content':'score candidates'},{'role':'user','content':text}]
        encoded=encode_candidate_prompt(CharacterTokenizer(),messages)
        self.assertEqual([c['location'] for c in encoded['candidates']],['pkg/"odd\\name.py:1','pkg/"odd\\name.py:20','other.py:1'])
        self.assertEqual(len({c['token_position'] for c in encoded['candidates']}),3)
        self.assertEqual(candidate_membership(encoded,[2]),[0,0,1])

    def test_completion_changes_labels_but_cannot_change_model_input(self):
        sample=numbered_example(fixture())[0];before=copy.deepcopy(sample)
        features=encode_candidate_prompt(CharacterTokenizer(),sample['prompt'])
        cid=features['candidates'][0]['candidate_id'];other=features['candidates'][1]['candidate_id']
        self.assertNotEqual(candidate_membership(features,[cid]),candidate_membership(features,[other]))
        sample['completion'][0]['content']='SECRET_ALTERNATIVE_ANSWER'
        self.assertEqual(features,encode_candidate_prompt(CharacterTokenizer(),sample['prompt']))
        self.assertEqual(before['prompt'],sample['prompt'])
        with self.assertRaisesRegex(ValueError,'prompt-only'):
            encode_candidate_prompt(CharacterTokenizer(),sample['prompt']+sample['completion'])

    def test_rejects_ambiguous_json_and_task_after_candidates(self):
        with self.assertRaises(ValueError):json_value_spans('{"goal":1,"goal":2}')
        payload={'structure':[{'path':'a.py','symbols':[[1,'name',0]]}],'goal':'too late'}
        with self.assertRaisesRegex(ValueError,'not visible'):
            encode_candidate_prompt(CharacterTokenizer(),[{'role':'user','content':json.dumps(payload)}])

    def test_balancing_respects_both_classes_and_has_gradients(self):
        try:import torch
        except ImportError:self.skipTest('Torch optional')
        logits=torch.tensor([0.,0.,0.,0.],requires_grad=True)
        loss=balanced_membership_loss(logits,[1,0,0,0]);loss.backward()
        torch.testing.assert_close(loss,torch.tensor(0.69314718))
        self.assertAlmostEqual(logits.grad[0].abs().item(),logits.grad[1:].abs().sum().item())
        with self.assertRaises(ValueError):balanced_membership_loss(logits,[0,0,0,0])
