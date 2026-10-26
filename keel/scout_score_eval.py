"""Fixed-policy candidate-score evaluation; no oracle answer count or generation."""
import os,json,time,hashlib
from pathlib import Path
from compass.progress import atomic_json
from .scout_tokenizer import file_hash
from .scout_adapter_eval import evaluation_inputs,score,validate_task_control,transfer_task_ids
from .scout_id_training import original_examples,training_task_universe
from .scout_candidate_ids import numbered_example,permutation_mode
from .scout_candidate_scoring import encode_candidate_prompt,candidate_membership,select_candidates,ranking_metrics


def evaluate_scores(dataset,tokenizer_run,training_run,output,*,evaluation_dataset=None,
                    candidate_permutation='original',checkpoint_step=None,threshold=0.5,max_items=8):
    permutation_mode(candidate_permutation)
    select_candidates([],[],threshold=threshold,max_items=max_items)
    assets,receipt,training,checkpoint=evaluation_inputs(dataset,tokenizer_run,training_run,checkpoint_step)
    if training.get('objective')!='candidate_scores' or 'candidate_head.pt' not in training['steps'][int(checkpoint.name.split('-')[1])-1]['checkpoint_files']:
        raise ValueError('Require completed hash-bound candidate-score checkpoint and head')
    if not training.get('candidate_head'):raise ValueError('Missing candidate-head architecture')
    original_examples(dataset)
    cohort=Path(evaluation_dataset) if evaluation_dataset is not None else Path(dataset)
    meta=json.loads((cohort/'export.json').read_text());validate_task_control(meta,False)
    filename='evaluation.jsonl' if evaluation_dataset is not None else 'development.jsonl'
    if file_hash(cohort/filename)!=meta['dataset_sha256']:raise ValueError('Evaluation data changed')
    if evaluation_dataset is None:rows,_=original_examples(cohort)
    else:
        used=training_task_universe(json.loads((Path(dataset)/'export.json').read_text()))
        if set(used)&transfer_task_ids(meta):raise ValueError('Training/transfer task overlap')
        for path,h in meta['inputs'].items():
            if file_hash(path)!=h:raise ValueError('Transfer evidence changed')
        rows=[json.loads(line) for line in (cohort/filename).read_text().splitlines()]
    indices=[i for i,r in enumerate(rows) if set(json.loads(r['completion'][0]['content']))=={'locations'}]
    if not indices:raise ValueError('Empty symbol cohort')
    output=Path(output);output.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    report={'status':'running','rows':[],'training_receipt_sha256':file_hash(Path(training_run)/'training/training.json'),
        'dataset_sha256':meta['dataset_sha256'],'checkpoint_step':int(checkpoint.name.split('-')[1]),
        'candidate_permutation':candidate_permutation,'selection_policy':{'threshold':threshold,'max_items':max_items,'empty_selection':'failure, no forced fallback'},
        'generations':0,'weight_updates':0,'hosted_calls':0,'production_promoted':False,
        'scope':'Exposed teacher-set agreement with fixed score policy, not official repair or independent generalization'}
    atomic_json(output/'report.json',report)
    try:
        os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_TORCH='1',USE_TF='0',USE_FLAX='0')
        from .scout_reproducibility import configure_environment,configure_torch,seed_training
        configure_environment('strict')
        import torch
        report['execution_policy']=configure_torch(torch,'strict');seed_training(torch,'strict')
        from transformers import AutoTokenizer,AutoModelForCausalLM
        from peft import PeftModel
        from .scout_lora import verify_weights
        from .scout_attention import register_attention
        tokenizer=AutoTokenizer.from_pretrained(str(assets),local_files_only=True,trust_remote_code=False)
        model=AutoModelForCausalLM.from_pretrained(str(verify_weights(training['weights'])),local_files_only=True,
            trust_remote_code=False,dtype=torch.float16,attn_implementation=register_attention()).to('cuda')
        model=PeftModel.from_pretrained(model,str(checkpoint),is_trainable=False);model.eval()
        head=torch.nn.Linear(training['candidate_head']['hidden_size'],1).float().to('cuda')
        head.load_state_dict(torch.load(checkpoint/'candidate_head.pt',map_location='cuda',weights_only=True));head.eval()
        for index in indices:
            print(f'[Candidate scores] sample {index+1}/{len(rows)}; {candidate_permutation}',flush=True)
            example=rows[index];actual,mapping,spec=numbered_example(example,permutation=candidate_permutation)
            features=encode_candidate_prompt(tokenizer,actual['prompt'])
            positions=[c['token_position'] for c in features['candidates']]
            ids=torch.tensor([features['input_ids']],device='cuda')
            with torch.inference_mode():
                hidden=model.get_base_model().model(input_ids=ids,use_cache=False).last_hidden_state
                probabilities=head(hidden[0,positions].float()).squeeze(-1).sigmoid().tolist()
            selected=select_candidates(features['candidates'],probabilities,threshold=threshold,max_items=max_items)
            mapped=json.dumps({'locations':[c['location'] for c in selected]})
            labels=candidate_membership(features,json.loads(actual['completion'][0]['content'])['candidate_ids'])
            metrics=score(example,mapped);metrics.update(ranking_metrics(probabilities,labels))
            report['rows'].append({'sample':index,'prompt_sha256':hashlib.sha256(json.dumps(actual['prompt'],sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                'candidate_mapping_sha256':hashlib.sha256(json.dumps(mapping).encode()).hexdigest(),
                'input_tokens':len(features['input_ids']),'mapped_output':mapped,'selected_ids':[c['candidate_id'] for c in selected],
                'candidate_scores':[{**c,'probability':v,'teacher_member':label} for c,v,label in zip(features['candidates'],probabilities,labels)],'score':metrics})
            atomic_json(output/'report.json',report)
            del ids,hidden;torch.cuda.empty_cache()
        assert {r['sample'] for r in report['rows']}==set(indices) and len(report['rows'])==len(indices)
        evaluation_inputs(dataset,tokenizer_run,training_run,checkpoint_step)
        original_examples(dataset)
        if file_hash(cohort/filename)!=report['dataset_sha256']:raise ValueError('Evaluation source changed')
        report.update(status='completed',summary={'samples':len(indices),
            'teacher_selection_equal':sum(r['score']['teacher_selection_equal'] for r in report['rows']),
            'contract_valid':sum(r['score']['contract_valid'] for r in report['rows']),
            'empty_selections':sum(not r['selected_ids'] for r in report['rows']),
            'teacher_macro_precision':sum(r['score']['teacher_precision'] for r in report['rows'])/len(indices),
            'teacher_macro_recall':sum(r['score']['teacher_recall'] for r in report['rows'])/len(indices),
            'teacher_mean_average_precision':sum(r['score']['teacher_average_precision'] for r in report['rows'])/len(indices)})
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__,error=str(error));raise
    finally:
        report['seconds']=time.monotonic()-started;atomic_json(output/'report.json',report)
    return report
