"""Paired exposed-development evaluation; no heldout or repair-success claim."""
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import time
from compass.progress import atomic_json
from .scout_tokenizer import file_hash,encode_sample
from .scout_lora import training_inputs,verify_weights,weight_hash,selected_positions,planned_updates
from .scout_data_audit import _selection
from .scout_data_review import inspect_selection


def score(example,text):
    schema=json.loads(example['prompt'][0]['content'].rsplit('Required output schema (JSON):\n',1)[1])
    request={'args':[example['prompt']],'kwargs':{'schema':schema}}
    response={'content':text};shape=_selection(request,response)
    review=inspect_selection(request,response,{})
    try:actual=json.loads(text);json_valid=True
    except ValueError:actual=None;json_valid=False
    target=json.loads(example['completion'][0]['content']);field=next(iter(target))
    predicted=actual.get(field,[]) if isinstance(actual,dict) else []
    if not isinstance(predicted,list) or any(not isinstance(v,str) for v in predicted):predicted=[]
    valid=not shape['issues'] and review['decision'] not in ('exclude_current_contract','hold_unsupported_input')
    duplicate=len(predicted)!=len(set(predicted))
    valid=valid and not duplicate
    expected=set(target[field]);chosen=set(predicted);overlap=len(expected&chosen)
    return {'json_valid':json_valid,'json_object':isinstance(actual,dict),'contract_valid':valid,
        'contract_issues':shape['issues']+review['violations']+(['duplicate_selection'] if duplicate else []),
        'teacher_selection_equal':valid and chosen==expected,
        'teacher_precision':overlap/len(chosen) if chosen else 0,
        'teacher_recall':overlap/len(expected) if expected else None,
        'scope':'Agreement with reviewed development teacher, not unique semantic optimum'}


def validate_task_control(exported,lookup_control):
    actual='known_name_lookup' if lookup_control else 'issue_selection'
    if exported.get('allowed_task_control',actual)!=actual:
        raise ValueError('Evaluation export is restricted to another task control')


def transfer_task_ids(exported):
    samples=exported.get('samples')
    if not isinstance(samples,list) or not samples:raise ValueError('Require transfer sample identity records')
    if any(not isinstance(row,dict) or not isinstance(row.get('instance_id'),str) or not row['instance_id'] for row in samples):
        raise ValueError('Invalid transfer task identity')
    return {row['instance_id'] for row in samples}


def evaluation_inputs(dataset,tokenizer_run,training_run,checkpoint_step=None):
    assets,receipt=training_inputs(dataset,tokenizer_run)
    root=Path(training_run);parent=json.loads((root/'report.json').read_text())
    path=root/'training/training.json';training=json.loads(path.read_text())
    if parent.get('identity',{}).get('objective','generation')!=training.get('objective','generation'):
        raise ValueError('Training objective drift')
    policy=parent.get('identity',{}).get('reproducibility','legacy')
    from .scout_reproducibility import validate_policy
    validate_policy(policy)
    if training.get('reproducibility','legacy')!=policy:raise ValueError('Training reproducibility policy drift')
    if policy=='strict' and (not training.get('execution_policy',{}).get('deterministic_algorithms') or
                            training.get('execution_policy',{}).get('cublas_workspace_config')!=':4096:8'):
        raise ValueError('Strict training execution configuration missing')
    expected=planned_updates(json.loads((Path(dataset)/'export.json').read_text())['sample_count'],training.get('epochs',1),training.get('max_updates'))
    if training.get('expected_steps',expected)!=expected:raise ValueError('Declared update budget changed')
    if (parent['status']!='passed' or training['status']!='passed' or
        parent['training_sha256']!=file_hash(path) or len(training['steps'])!=expected or
        training['dataset_sha256']!=receipt['identity']['inputs']['development.jsonl']):
        raise ValueError('Require completed hash-bound planned development training')
    step=expected if checkpoint_step is None else checkpoint_step
    if type(step) is not int or not 1<=step<=expected:raise ValueError('Checkpoint outside completed training')
    checkpoint=root/f'training/step-{step}'
    for name,identity in training['steps'][step-1]['checkpoint_files'].items():
        if Path(name).name!=name or weight_hash(checkpoint/name)!=identity:raise ValueError('Adapter checkpoint changed')
    return assets,receipt,training,checkpoint


def summarize(rows):
    result={}
    for arm in ('base','adapter'):
        selected=[r for r in rows if r['arm']==arm]
        tokens=sum(r['labelled_tokens'] for r in selected)
        result[arm]={'samples':len(selected),'json_valid':sum(r['score']['json_valid'] for r in selected),
            'contract_valid':sum(r['score']['contract_valid'] for r in selected),
            'teacher_selection_equal':sum(r['score']['teacher_selection_equal'] for r in selected),
            'censored_generations':sum(r['finish_reason']!='eos' for r in selected),
            'teacher_token_nll':sum(r['teacher_nll']*r['labelled_tokens'] for r in selected)/tokens if tokens else None}
    return result


def cached_baseline(cached,report,count,indices=None):
    if (cached['status']!='completed' or cached['dataset_sha256']!=report['dataset_sha256'] or
        cached['training_receipt_sha256']!=report['training_receipt_sha256'] or cached['generation']!=report['generation']):
        raise ValueError('Cached baseline identity/configuration changed')
    for field in ('representation','symbol_only','candidate_permutation','task_control','lookup_presentation'):
        if cached.get(field)!=report.get(field):raise ValueError('Cached baseline interface changed')
    baseline=[row for row in cached['rows'] if row['arm']=='base']
    expected=set(range(count)) if indices is None else set(indices)
    if len(baseline)!=len(expected) or {r['sample'] for r in baseline}!=expected:
        raise ValueError('Cached baseline incomplete')
    return baseline


def validate_cached_prompts(rows,samples,indices,representation,lookup_control,lookup_presentation,candidate_permutation):
    """Reconstruct expected full prompts without model execution before cache reuse."""
    for index in indices:
        example=samples[index]
        if representation=='candidate_ids':
            from .scout_candidate_ids import numbered_example,lookup_example
            if lookup_control:example=lookup_example(example,presentation=lookup_presentation)[0]
            else:example=numbered_example(example,permutation=candidate_permutation)[0]
        expected=hashlib.sha256(json.dumps(example['prompt'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        row=next(r for r in rows if r['sample']==index)
        if row.get('prompt_sha256')!=expected:raise ValueError('Cached baseline prompt changed')


def rescore(dataset,source,output):
    """Reuse immutable raw generations after a scorer correction, without inference."""
    dataset,source,output=map(Path,(dataset,source,output))
    path=source/'report.json';identity=file_hash(path)
    report=json.loads(path.read_text(encoding='utf-8'))
    filename=report.get('cohort_file','development.jsonl')
    if filename not in ('development.jsonl','evaluation.jsonl'):raise ValueError('Unknown evaluation cohort file')
    if report['status']!='completed' or file_hash(dataset/filename)!=report['dataset_sha256']:
        raise ValueError('Require completed comparison and unchanged dataset')
    samples=[json.loads(line) for line in (dataset/filename).read_text(encoding='utf-8').splitlines()]
    keys=[(row['arm'],row['sample']) for row in report['rows']]
    if len(keys)!=2*len(samples) or set(keys)!={(arm,i) for arm in ('base','adapter') for i in range(len(samples))}:
        raise ValueError('Missing or duplicate paired output')
    output.mkdir(parents=True,exist_ok=False)
    for row in report['rows']:row['score']=score(samples[row['sample']],row['output'])
    report['summary']=summarize(report['rows'])
    report['rescore']={'source':str(source.resolve()),'source_report_sha256':identity,'new_generation_calls':0,
        'scorer_sha256':file_hash(Path(__file__)),'correction':'JSON parse validity separated from object/selection validity'}
    if file_hash(path)!=identity or file_hash(dataset/filename)!=report['dataset_sha256']:
        raise ValueError('Rescore input changed')
    atomic_json(output/'report.json',report)
    return report


def evaluate(dataset,tokenizer_run,training_run,output,*,evaluation_dataset=None,checkpoint_step=None,reuse_base_from=None,
             representation='locations',symbol_only=False,lookup_control=False,lookup_presentation='original',candidate_permutation='original'):
    from .scout_candidate_ids import permutation_mode
    permutation_mode(candidate_permutation)
    if candidate_permutation!='original' and (representation!='candidate_ids' or lookup_control):
        raise ValueError('Permutation requires issue-selection candidate IDs')
    if representation not in ('locations','candidate_ids'):raise ValueError('Unknown representation')
    if representation=='candidate_ids' and not symbol_only:raise ValueError('Candidate IDs ablation requires symbol-only cohort')
    if lookup_control and representation!='candidate_ids':raise ValueError('Lookup control requires candidate-ID representation')
    if lookup_presentation not in ('original','without_goal','flat'):raise ValueError('Unknown lookup presentation')
    if not lookup_control and lookup_presentation!='original':raise ValueError('Lookup presentation requires lookup control')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_TORCH='1',USE_TF='0',USE_FLAX='0')
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer
    from peft import PeftModel
    from .scout_attention import register_attention
    assets,receipt,training,checkpoint=evaluation_inputs(dataset,tokenizer_run,training_run,checkpoint_step)
    if training.get('objective','generation')!='generation':raise ValueError('Candidate scores require their dedicated evaluator')
    cohort=Path(evaluation_dataset) if evaluation_dataset is not None else Path(dataset)
    filename='evaluation.jsonl' if evaluation_dataset is not None else 'development.jsonl'
    cohort_export=json.loads((cohort/'export.json').read_text())
    validate_task_control(cohort_export,lookup_control)
    if evaluation_dataset is not None:
        if cohort_export['status']!='exported_development_transfer_only' or cohort_export['training_allowed'] is not False:
            raise ValueError('Require evaluation-only development transfer export')
        from .scout_id_training import training_task_universe
        trained_export=json.loads((Path(dataset)/'export.json').read_text())
        if trained_export.get('representation') in ('subset_candidate_ids','permuted_candidate_ids'):
            from .scout_id_training import original_examples
            original_examples(Path(dataset))
        used=training_task_universe(trained_export)
        if set(used)&transfer_task_ids(cohort_export):raise ValueError('Transfer task was in training')
        for name,identity in cohort_export['inputs'].items():
            if file_hash(name)!=identity:raise ValueError('Transfer approval/input drift')
    cohort_hash=file_hash(cohort/filename)
    if cohort_hash!=cohort_export['dataset_sha256']:raise ValueError('Evaluation cohort changed')
    scoring_source=None
    if evaluation_dataset is None and cohort_export.get('representation') in ('mixed_files_candidate_ids','mixed_files_candidate_ids_with_lookup','lookup_only_candidate_ids','lookup_diverse_candidate_ids','subset_candidate_ids','permuted_candidate_ids'):
        if representation!='candidate_ids' or not symbol_only:
            raise ValueError('ID-trained evaluation requires explicit candidate-ID symbol scoring')
        from .scout_id_training import original_examples
        samples,scoring_source=original_examples(cohort)
    else:
        samples=[json.loads(line) for line in (cohort/filename).read_text(encoding='utf-8').splitlines()]
    expected_indices={i for i,row in enumerate(samples) if not symbol_only or 'locations' in json.loads(row['completion'][0]['content'])}
    if not expected_indices:raise ValueError('Empty evaluation cohort')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    report={'status':'running','scope':'Exposed development transfer controls' if evaluation_dataset is not None else 'Exposed training controls; descriptive development comparison only',
        'production_promoted':False,'heldout':False,'weight_updates':0,'rows':[],
        'dataset_sha256':cohort_hash,'cohort_file':filename,
        'training_dataset_sha256':receipt['identity']['inputs']['development.jsonl'],
        'checkpoint_step':int(checkpoint.name.split('-')[1]),
        'representation':representation,'symbol_only':symbol_only,
        'candidate_permutation':candidate_permutation,
        'task_control':'known_name_lookup' if lookup_control else 'issue_selection',
        'lookup_presentation':lookup_presentation if lookup_control else None,
        'teacher_nll_scope':'Representation-specific teacher-token NLL; not comparable across output encodings',
        'training_receipt_sha256':file_hash(Path(training_run)/'training/training.json'),
        'generation':{'do_sample':False,'max_new_tokens':256,'max_time':45,'thinking':False,
                      'use_cache':True,'logits_to_keep':1,'grammar_constraints':False},
        'arm_order':'base then adapter; timing descriptive, order not randomized'}
    if scoring_source is not None:report['original_scoring_source']=scoring_source
    atomic_json(output/'report.json',report)
    cache_path=None
    try:
        if reuse_base_from is not None:
            cache_path=Path(reuse_base_from)/'report.json';cached=json.loads(cache_path.read_text())
            report['rows']=cached_baseline(cached,report,len(expected_indices),expected_indices)
            validate_cached_prompts(report['rows'],samples,expected_indices,representation,
                                    lookup_control,lookup_presentation,candidate_permutation)
            report['reused_base']={'source':str(cache_path),'sha256':file_hash(cache_path),
                'scope':'Historical base generations/NLL/timings reused after identity/configuration checks'}
        if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
        weights=verify_weights(training['weights'])
        tokenizer=AutoTokenizer.from_pretrained(str(assets),local_files_only=True,trust_remote_code=False)
        model=AutoModelForCausalLM.from_pretrained(str(weights),local_files_only=True,trust_remote_code=False,
            dtype=torch.float16,attn_implementation=register_attention()).to('cuda')
        model=PeftModel.from_pretrained(model,str(checkpoint),is_trainable=False);model.eval()
        if len(samples)!=cohort_export.get('original_sample_count',cohort_export['sample_count']):raise ValueError('Evaluation sample count changed')
        for arm in (('adapter',) if reuse_base_from is not None else ('base','adapter')):
            with model.disable_adapter() if arm=='base' else nullcontext():
                for index,example in enumerate(samples):
                    if symbol_only and 'locations' not in json.loads(example['completion'][0]['content']):continue
                    print(f'[Scout comparison] {arm} sample {index+1}/{len(samples)}',flush=True)
                    actual_example=example;scoring_example=example;mapping=None;spec=None;lookup=None
                    if representation=='candidate_ids':
                        from .scout_candidate_ids import numbered_example,lookup_example
                        if lookup_control:actual_example,mapping,spec,scoring_example,lookup=lookup_example(example,presentation=lookup_presentation)
                        else:actual_example,mapping,spec=numbered_example(example,permutation=candidate_permutation)
                    encoded=encode_sample(tokenizer,actual_example);prefix=encoded['metrics']['prompt_tokens']
                    ids=torch.tensor([encoded['input_ids']],device='cuda');positions=selected_positions(encoded['labels'])
                    targets=torch.tensor([encoded['labels'][p+1] for p in positions],device='cuda')
                    torch.cuda.reset_peak_memory_stats()
                    with torch.inference_mode():
                        base=model.get_base_model()
                        hidden=base.model(input_ids=ids,use_cache=False).last_hidden_state
                        logits=base.lm_head(hidden[0,positions]).float()
                        nll=torch.nn.functional.cross_entropy(logits,targets).item()
                        del hidden,logits,targets,ids
                        # Only prompt/prefill tokens go to generation; target stays in scorer.
                        prompt=torch.tensor([encoded['input_ids'][:prefix]],device='cuda')
                        generation_started=time.monotonic()
                        generated=model.generate(input_ids=prompt,attention_mask=torch.ones_like(prompt),
                            do_sample=False,max_new_tokens=256,max_time=45,use_cache=True,logits_to_keep=1,
                            pad_token_id=tokenizer.pad_token_id,eos_token_id=tokenizer.eos_token_id,
                            temperature=None,top_p=None,top_k=None)
                        torch.cuda.synchronize();elapsed=time.monotonic()-generation_started
                    tokens=generated[0,prefix:].tolist();text=tokenizer.decode(tokens,skip_special_tokens=True)
                    mapped=text;id_error=None
                    if mapping is not None:
                        from .scout_candidate_ids import decode_ids
                        try:mapped=decode_ids(text,mapping,spec)
                        except ValueError as error:id_error=str(error);mapped=text
                    reason='eos' if tokens and tokens[-1]==tokenizer.eos_token_id else ('token_limit' if len(tokens)>=256 else 'time_limit')
                    report['rows'].append({'arm':arm,'sample':index,'prompt_tokens':prefix,
                        'prompt_sha256':hashlib.sha256(json.dumps(actual_example['prompt'],sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                        'labelled_tokens':len(positions),'teacher_nll':nll,'output':text,'generated_tokens':len(tokens),
                        'finish_reason':reason,'generation_seconds':elapsed,'score':score(scoring_example,mapped),
                        'peak_allocated_bytes':torch.cuda.max_memory_allocated()})
                    if mapping is not None:
                        report['rows'][-1].update(mapped_output=mapped if id_error is None else None,
                            candidate_id_error=id_error,candidate_id_valid=id_error is None,candidate_count=len(mapping),
                            candidate_mapping_sha256=hashlib.sha256(json.dumps(mapping).encode()).hexdigest())
                        if id_error is not None:
                            report['rows'][-1]['score'].update(contract_valid=False,teacher_selection_equal=False)
                            report['rows'][-1]['score']['contract_issues'].append('candidate_id_interface_invalid')
                    if lookup is not None:
                        report['rows'][-1]['lookup_control']=lookup
                        report['rows'][-1]['score']['scope']='Deterministic known-name lookup agreement, not repair/localization quality'
                    atomic_json(output/'report.json',report)
                    del prompt,generated;torch.cuda.empty_cache()
        evaluation_inputs(dataset,tokenizer_run,training_run,checkpoint_step)
        if file_hash(cohort/filename)!=cohort_hash:raise ValueError('Evaluation data changed during run')
        if cache_path is not None and file_hash(cache_path)!=report['reused_base']['sha256']:
            raise ValueError('Cached baseline changed during evaluation')
        if scoring_source is not None:original_examples(cohort)
        keys=[(row['arm'],row['sample']) for row in report['rows']]
        if len(keys)!=len(set(keys)) or set(keys)!={(arm,i) for arm in ('base','adapter') for i in expected_indices}:
            raise ValueError('Missing or duplicate evaluation outputs')
        report.update(status='completed',summary=summarize(report['rows']))
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__,error=str(error)[:2000]);raise
    finally:
        report['seconds']=round(time.monotonic()-started,3);atomic_json(output/'report.json',report)
    return report
