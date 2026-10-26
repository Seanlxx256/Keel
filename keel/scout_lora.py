"""Four-example development LoRA resource smoke, not a quality evaluation."""
import json
import hashlib
import os
from pathlib import Path
import time
from compass.progress import atomic_json
from .scout_tokenizer import MODEL,REVISION,file_hash,encode_sample,verify_assets

PINS=('transformers==4.57.6','peft==0.17.1','jinja2==3.1.6')


def weight_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):digest.update(block)
    return digest.hexdigest()


def training_inputs(dataset,tokenizer_run):
    dataset=Path(dataset);run=Path(tokenizer_run)
    report=json.loads((run/'report.json').read_text(encoding='utf-8'))
    if report['status']!='passed' or file_hash(run/'check.json')!=report['check_sha256']:
        raise ValueError('Require passed hash-bound tokenizer check')
    for name,expected in report['identity']['inputs'].items():
        if file_hash(dataset/name)!=expected:raise ValueError('Reviewed dataset changed')
    assets=Path(report['assets']);verify_assets(assets)
    if file_hash(assets/'assets.json')!=report['assets_sha256']:raise ValueError('Assets receipt changed')
    return assets,report


def download(directory,cache):
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
    from huggingface_hub import snapshot_download
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    source=Path(snapshot_download(MODEL,revision=REVISION,cache_dir=str(cache),token=False,
        allow_patterns=['config.json','model.safetensors']))
    # Reference retained HF cache instead of making a second multi-GB copy.
    files={name:weight_hash(source/name) for name in ('config.json','model.safetensors')}
    value={'model':MODEL,'revision':REVISION,'directory':str(source),'files':files}
    atomic_json(directory/'weights.json',value)
    return value


def verify_weights(receipt):
    if receipt['model']!=MODEL or receipt['revision']!=REVISION or set(receipt['files'])!={'config.json','model.safetensors'}:
        raise ValueError('Unpinned weight assets')
    root=Path(receipt['directory'])
    for name,identity in receipt['files'].items():
        if weight_hash(root/name)!=identity:raise ValueError('Weights changed')
    return root


def selected_positions(labels):
    """Causal hidden positions predicting labelled tokens, shifted exactly once."""
    return [i-1 for i,value in enumerate(labels) if i>0 and value!=-100]


def planned_updates(sample_count,epochs,max_updates=None):
    if type(sample_count) is not int or sample_count<1 or type(epochs) is not int or epochs<1:
        raise ValueError('Positive sample count and epochs required')
    total=sample_count*epochs
    if max_updates is not None:
        if type(max_updates) is not int or not 1<=max_updates<=total:
            raise ValueError('Update budget outside planned epoch schedule')
        return max_updates
    return total


def training_schedule(sample_lengths,epochs,max_updates=None):
    if type(epochs) is not int or epochs<1 or not sample_lengths:raise ValueError('Explicit positive epochs and nonempty samples required')
    order=sorted(range(len(sample_lengths)),key=lambda i:sample_lengths[i],reverse=True)
    count=planned_updates(len(sample_lengths),epochs,max_updates)
    return [(epoch,index) for epoch in range(1,epochs+1) for index in order][:count]


def validate_objective(objective):
    if objective not in ('generation','candidate_scores'):raise ValueError('Unknown training objective')
    return objective


def train(dataset,tokenizer_run,weights,output,*,epochs=1,max_updates=None,reproducibility='legacy',objective='generation'):
    validate_objective(objective)
    from .scout_reproducibility import configure_environment,configure_torch,rng_state,seed_training
    configure_environment(reproducibility)
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    os.environ['USE_TF']='0';os.environ['USE_FLAX']='0';os.environ['USE_TORCH']='1'
    import torch
    execution_policy=configure_torch(torch,reproducibility)
    from transformers import AutoModelForCausalLM,AutoTokenizer
    from peft import LoraConfig,get_peft_model
    from .scout_attention import register_attention
    assets,receipt=training_inputs(dataset,tokenizer_run)
    weights=json.loads(Path(weights).read_text(encoding='utf-8'));source=verify_weights(weights)
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();seed_training(torch,reproducibility,42)
    report={'status':'running','scope':'Approved exposed development controls; no heldout quality claim',
        'steps':[],'seed':42,'lora':{'r':4,'alpha':8,'dropout':0,'target_modules':['q_proj','v_proj']},
        'dataset_sha256':receipt['identity']['inputs']['development.jsonl'],'weights':weights,'model_calls':0,
        'reproducibility':reproducibility,'execution_policy':execution_policy,'objective':objective}
    atomic_json(output/'training.json',report)
    try:
        if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable; no CPU fallback')
        report['gpu']=torch.cuda.get_device_name(0);report['torch']=torch.__version__
        report['phase']='load';atomic_json(output/'training.json',report)
        tokenizer=AutoTokenizer.from_pretrained(str(assets),local_files_only=True,trust_remote_code=False)
        raw=[json.loads(line) for line in (Path(dataset)/'development.jsonl').read_text(encoding='utf-8').splitlines()]
        if objective=='candidate_scores':
            from .scout_candidate_scoring import encode_candidate_prompt,candidate_membership,balanced_membership_loss
            examples=[]
            for row in raw:
                features=encode_candidate_prompt(tokenizer,row['prompt'])
                labels=candidate_membership(features,json.loads(row['completion'][0]['content'])['candidate_ids'])
                examples.append({**features,'labels':labels})
        else:examples=[encode_sample(tokenizer,row) for row in raw]
        schedule=training_schedule([len(e['input_ids']) for e in examples],epochs,max_updates)
        report.update(epochs=epochs,sample_count=len(examples),learning_rate=1e-4,
                      order='longest first, same order each epoch; seed42',expected_steps=len(schedule),max_updates=max_updates)
        attention=register_attention()
        report['attention']={'implementation':attention,'cuda_backend':'EFFICIENT_ATTENTION','enable_gqa':False,
                             'scope':'Explicit repeated KV; no math fallback on CUDA, unchanged full context'}
        print('[LoRA] load pinned weights; float16, efficient repeated-KV SDPA, gradient checkpointing',flush=True)
        model=AutoModelForCausalLM.from_pretrained(str(source),local_files_only=True,trust_remote_code=False,
            dtype=torch.float16,attn_implementation=attention).to('cuda')
        model=get_peft_model(model,LoraConfig(r=4,lora_alpha=8,lora_dropout=0,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM'))
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
        model.config.use_cache=False;model.train()
        trainable={name:p for name,p in model.named_parameters() if p.requires_grad}
        if not trainable or any('lora_' not in name for name in trainable):raise ValueError('Non-adapter trainable parameters')
        head=None
        if objective=='candidate_scores':
            head=torch.nn.Linear(model.config.hidden_size,1).float().to('cuda')
            trainable.update({'candidate_head.'+name:p for name,p in head.named_parameters()})
            report['candidate_head']={'hidden_size':model.config.hidden_size,'output_size':1,
                'parameters':sum(p.numel() for p in head.parameters()),'loss':'class-balanced teacher membership BCE',
                'input':'prompt only; last fully contained token per candidate','causal_visibility':'Earlier candidates cannot see later catalog entries'}
        report['trainable_parameters']=sum(p.numel() for p in trainable.values())
        optimizer=torch.optim.AdamW(trainable.values(),lr=1e-4)
        # Longest first exposes resource limits before cheaper samples consume time.
        for epoch,index in schedule:
            example=examples[index];torch.cuda.reset_peak_memory_stats();optimizer.zero_grad(set_to_none=True)
            print(f'[LoRA] epoch {epoch}/{epochs}; sample {index+1}; full tokens={len(example["input_ids"])}',flush=True)
            report.update(phase='sample',active_sample=index);atomic_json(output/'training.json',report)
            ids=torch.tensor([example['input_ids']],device='cuda')
            if head is not None:
                positions=[c['token_position'] for c in example['candidates']]
                targets=example['labels']
            else:
                positions=selected_positions(example['labels'])
                targets=torch.tensor([example['labels'][p+1] for p in positions],device='cuda')
            before={name:p.detach().cpu().clone() for name,p in trainable.items()}
            base=model.get_base_model()
            hidden=base.model(input_ids=ids,use_cache=False).last_hidden_state
            # Same completion-only causal CE, without allocating prompt vocabulary logits.
            if head is not None:
                logits=head(hidden[0,positions,:].float()).squeeze(-1)
                loss=balanced_membership_loss(logits,targets)
            else:
                logits=base.lm_head(hidden[0,positions,:]).float()
                loss=torch.nn.functional.cross_entropy(logits,targets)
            if not torch.isfinite(loss):raise ValueError('Nonfinite loss')
            loss.backward()
            grads=[p.grad for p in trainable.values() if p.grad is not None]
            if not grads or not all(torch.isfinite(g).all().item() for g in grads):raise ValueError('Missing/nonfinite gradients')
            norm=torch.nn.utils.clip_grad_norm_(list(trainable.values()),1.0)
            if not torch.isfinite(norm) or norm.item()==0:raise ValueError('Zero/nonfinite gradient norm')
            optimizer.step();torch.cuda.synchronize()
            changed=sum(not torch.equal(before[name],p.detach().cpu()) for name,p in trainable.items())
            if not changed:raise ValueError('Optimizer did not change adapter weights')
            step={'sample':index,'epoch':epoch,'input_tokens':len(example['input_ids']),'labelled_tokens':len(positions) if head is None else 0,
                'loss':loss.item(),'gradient_norm':norm.item(),'changed_adapter_tensors':changed,
                'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved()}
            if head is not None:
                step['labelled_candidates']=len(positions)
                step['changed_parameter_tensors']=changed
                step['changed_adapter_tensors']=sum(not torch.equal(before[name],p.detach().cpu()) for name,p in trainable.items() if 'lora_' in name)
            destination=output/f'step-{len(report["steps"])+1}';temporary=output/(destination.name+'.tmp')
            model.save_pretrained(temporary,safe_serialization=True)
            if head is not None:torch.save(head.state_dict(),temporary/'candidate_head.pt')
            torch.save(optimizer.state_dict(),temporary/'optimizer.pt')
            torch.save(rng_state(torch),temporary/'rng_state.pt')
            step['checkpoint_files']={p.name:weight_hash(p) for p in temporary.iterdir() if p.is_file()}
            atomic_json(temporary/'step.json',step);temporary.rename(destination)
            report['steps'].append(step);atomic_json(output/'training.json',report)
            del hidden,logits,loss,ids,targets;torch.cuda.empty_cache()
        training_inputs(dataset,tokenizer_run)
        report.update(status='passed',phase='completed')
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__,error=str(error)[:2000])
        if torch.cuda.is_available():
            report['failure_peak_allocated_bytes']=torch.cuda.max_memory_allocated()
        raise
    finally:
        report['seconds']=round(time.monotonic()-started,3);atomic_json(output/'training.json',report)
    return report
