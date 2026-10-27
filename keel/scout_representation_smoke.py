"""Longest full-input resource/gradient check, not a localization evaluation."""
import json
import os
import time
from pathlib import Path
from compass.progress import atomic_json


def run(dataset, tokenizer_run, weights, output, *, input_mode, readout_mode):
    from .scout_lora import training_inputs, verify_weights, weight_hash
    from .scout_tokenizer import file_hash
    from .scout_candidate_scoring import encode_scoring_variant, candidate_membership, balanced_membership_loss
    from .scout_reproducibility import configure_environment, configure_torch, seed_training
    if input_mode not in ('numbered','without_ids') or readout_mode not in ('candidate_end','after_catalog'):
        raise ValueError('Unknown representation policy')
    assets, receipt = training_inputs(dataset, tokenizer_run)
    weights = Path(weights)
    weight_receipt = json.loads(weights.read_text())
    source = verify_weights(weight_receipt)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = dict(status='running', input_mode=input_mode, readout_mode=readout_mode,
        dataset_sha256=receipt['identity']['inputs']['development.jsonl'],
        weights_receipt_sha256=file_hash(weights), implementation_sha256=file_hash(__file__),
        encoder_sha256=file_hash(Path(__file__).with_name('scout_candidate_scoring.py')),
        optimizer_updates=0, hosted_calls=0, generations=0,
        scope='One longest-input forward/backward; no optimizer, quality score or promotion')
    atomic_json(output/'report.json', report)
    try:
        configure_environment('strict')
        os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', USE_TF='0', USE_FLAX='0')
        import torch
        report['execution_policy'] = configure_torch(torch,'strict'); seed_training(torch,'strict',42)
        if not torch.cuda.is_available(): raise RuntimeError('CUDA unavailable; no CPU fallback')
        from transformers import AutoTokenizer, AutoModelForCausalLM
        from peft import LoraConfig, get_peft_model
        from .scout_attention import register_attention
        tokenizer = AutoTokenizer.from_pretrained(str(assets),local_files_only=True,trust_remote_code=False)
        rows = [json.loads(line) for line in (Path(dataset)/'development.jsonl').read_text().splitlines()]
        # Inspect all lengths before choosing a sample; teacher labels cannot affect selection.
        encoded = [encode_scoring_variant(tokenizer,row['prompt'],input_mode=input_mode,readout_mode=readout_mode) for row in rows]
        index = max(range(len(encoded)), key=lambda i:(len(encoded[i]['input_ids']),-i))
        features = encoded[index]
        labels = candidate_membership(features,json.loads(rows[index]['completion'][0]['content'])['candidate_ids'])
        report.update(sample=index, input_tokens=len(features['input_ids']), candidates=len(labels),
            selection='Longest complete input; earliest sample breaks ties',
            input_sha256=__import__('hashlib').sha256(json.dumps(features['input_ids']).encode()).hexdigest(),
            gpu=torch.cuda.get_device_name(0),gpu_total_bytes=torch.cuda.get_device_properties(0).total_memory,
            phase='load')
        atomic_json(output/'report.json',report)
        print(f"[Representation smoke] {input_mode}/{readout_mode}; tokens={report['input_tokens']}; load",flush=True)
        base = AutoModelForCausalLM.from_pretrained(str(source),local_files_only=True,trust_remote_code=False,
            dtype=torch.float16,attn_implementation=register_attention()).to('cuda')
        model = get_peft_model(base,LoraConfig(r=4,lora_alpha=8,lora_dropout=0,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM'))
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
        model.config.use_cache=False; model.train()
        head = torch.nn.Linear(model.config.hidden_size,1).float().to('cuda')
        ids = torch.tensor([features['input_ids']],device='cuda')
        positions = [c['token_position'] for c in features['candidates']]
        torch.cuda.reset_peak_memory_stats()
        report['phase']='forward'; atomic_json(output/'report.json',report)
        hidden = model.get_base_model().model(input_ids=ids,use_cache=False).last_hidden_state
        loss = balanced_membership_loss(head(hidden[0,positions].float()).squeeze(-1),labels)
        if not torch.isfinite(loss): raise ValueError('Nonfinite loss')
        report['phase']='backward'; atomic_json(output/'report.json',report)
        print('[Representation smoke] backward',flush=True)
        loss.backward(); torch.cuda.synchronize()
        def gradient_summary(parameters):
            grads=[p.grad for p in parameters if p.grad is not None]
            if not grads or not all(torch.isfinite(g).all().item() for g in grads):
                raise ValueError('Missing/nonfinite gradients')
            norm=sum(g.float().norm().item() for g in grads)
            if norm<=0: raise ValueError('Zero gradient')
            return norm
        report.update(lora_gradient_norm_sum=gradient_summary(p for p in model.parameters() if p.requires_grad),
            head_gradient_norm_sum=gradient_summary(head.parameters()), loss=loss.item(),
            peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved())
        training_inputs(dataset,tokenizer_run)
        if file_hash(weights)!=report['weights_receipt_sha256']: raise ValueError('Weights receipt changed')
        report.update(status='passed',phase='completed')
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__,error=str(error))
        raise
    finally:
        report['seconds']=time.monotonic()-started
        atomic_json(output/'report.json',report)
    return report
