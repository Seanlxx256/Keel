"""Explicit proposal capacity policy; local counting never implies provider exactness."""
import base64
import hashlib
import json
import math
from pathlib import Path

from .core import BudgetExceeded, InputCapacityExceeded


def validate_policy(policy):
    required={'model_context_tokens','max_input_tokens','safety_tokens','max_request_bytes'}
    if (not isinstance(policy,dict) or not required<=set(policy)
            or set(policy)-required-{'local_tokenizer'}
            or any(type(policy[k]) is not int or policy[k]<=0 for k in required)):
        raise ValueError('Proposal context policy requires positive model_context_tokens/max_input_tokens/safety_tokens/max_request_bytes')
    if policy['safety_tokens']>=policy['model_context_tokens']:
        raise ValueError('Context safety reserve must be smaller than model context')
    if 'local_tokenizer' in policy and (not isinstance(policy['local_tokenizer'],str) or not policy['local_tokenizer']):
        raise ValueError('local_tokenizer must name an offline encoding JSON file')
    return policy


def estimate_input(messages,schema,policy):
    """Count serialized text with an offline encoding, or visibly fall back to bytes.

    Offline format: name, pat_str, mergeable_ranks (base64-token -> rank),
    special_tokens. No model-name inference, HTTP requests or asset downloads.
    Message framing/schema differences still require the configured safety reserve.
    """
    text=json.dumps({'messages':messages,'schema':schema},ensure_ascii=False)
    result={'input_estimate':len(text.encode()),'estimator':'utf8_bytes_conservative',
            'provider_exact':False}
    if policy.get('local_tokenizer'):
        try:
            path=Path(policy['local_tokenizer'])
            if path.stat().st_size>20_000_000:
                raise ValueError('Offline encoding exceeds20MB')
            data=json.loads(path.read_text(encoding='utf-8'))
            import tiktoken
            ranks={base64.b64decode(k,validate=True):v for k,v in data['mergeable_ranks'].items()}
            encoding=tiktoken.Encoding(name=data['name'],pat_str=data['pat_str'],
                mergeable_ranks=ranks,special_tokens=data['special_tokens'])
            result.update(input_estimate=len(encoding.encode(text,disallowed_special=())),
                          estimator='offline_tiktoken',tokenizer_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        except (ImportError,OSError,ValueError,KeyError,TypeError) as error:
            result['fallback_reason']=type(error).__name__
    return result


def admission(messages,schema,policy,output,budget):
    validate_policy(policy)
    budget.check()
    estimate=estimate_input(messages,schema,policy)
    reserved=estimate['input_estimate']+policy['safety_tokens']
    model_available=policy['model_context_tokens']-output
    per_call_available=policy['max_input_tokens']
    remaining=budget.limits.max_tokens-budget.tokens-output
    report={**estimate,'reserved_input_tokens':reserved,'output_reserved_tokens':output,
            'policy_sha256':hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest(),
            'safety_reserved_tokens':policy['safety_tokens'],
            'model_available_input_tokens':model_available,
            'per_call_input_limit_tokens':per_call_available,
            'remaining_available_input_tokens':remaining,
            'effective_input_limit_tokens':min(model_available,per_call_available,remaining)}
    # Depleted global budget is not recoverable by repeatedly selecting source.
    if reserved>remaining:
        raise BudgetExceeded('Insufficient remaining token budget for proposal input, safety and output')
    if reserved>min(model_available,per_call_available):
        error=InputCapacityExceeded('Proposal exceeds configured model/per-call input token capacity')
        error.context_metrics=report
        raise error
    return report


def calibration_report(events):
    """Summarize observed errors only; never change active policy or budgets."""
    groups={}
    for row in events:
        if row.get('event')!='proposal_token_estimate_observed':
            continue
        predicted,actual=row.get('estimated_input_tokens'),row.get('actual_input_tokens')
        if type(predicted) is not int or predicted<=0 or type(actual) is not int or actual<0:
            continue
        key=(row.get('model'),row.get('estimator'),row.get('policy_sha256'),row.get('tokenizer_sha256'))
        groups.setdefault(key,[]).append((predicted,actual,row.get('reserved_input_tokens')))
    result=[]
    for key,rows in groups.items():
        ratios=sorted(actual/predicted for predicted,actual,_ in rows)
        result.append({'model':key[0],'estimator':key[1],'policy_sha256':key[2],
            'tokenizer_sha256':key[3],'samples':len(rows),
            'p95_actual_over_estimate':ratios[math.ceil(.95*len(ratios))-1],
            'maximum_underestimate_tokens':max(0,max(a-p for p,a,_ in rows)),
            'under_reserved_samples':sum(type(r) is int and a>r for _,a,r in rows)})
    return {'groups':result,'scope':'Observed input-estimation error; no automatic threshold tuning or monetary-cost claim.'}
