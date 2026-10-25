"""Explicit proposal capacity policy; local counting never implies provider exactness."""
import base64
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

from .core import BudgetExceeded, InputCapacityExceeded


def validate_policy(policy):
    required={'model_context_tokens','max_input_tokens','safety_tokens','max_request_bytes'}
    if (not isinstance(policy,dict) or not required<=set(policy)
            or set(policy)-required-{'local_tokenizer','recover_capacity','require_local_tokenizer','local_tokenizer_sha256'}
            or any(type(policy[k]) is not int or policy[k]<=0 for k in required)):
        raise ValueError('Proposal context policy requires positive model_context_tokens/max_input_tokens/safety_tokens/max_request_bytes')
    if 'require_local_tokenizer' in policy and type(policy['require_local_tokenizer']) is not bool:
        raise ValueError('require_local_tokenizer must be boolean')
    if policy.get('require_local_tokenizer') and not policy.get('local_tokenizer'):
        raise ValueError('Required tokenizer needs an explicit offline encoding')
    if 'local_tokenizer_sha256' in policy:
        import re
        if not isinstance(policy['local_tokenizer_sha256'], str) or not re.fullmatch('[a-f0-9]{64}',policy['local_tokenizer_sha256']):
            raise ValueError('Invalid offline tokenizer hash')
    if 'recover_capacity' in policy and type(policy['recover_capacity']) is not bool:
        raise ValueError('recover_capacity must be boolean')
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
            raw=path.read_bytes();identity=hashlib.sha256(raw).hexdigest()
            if policy.get('local_tokenizer_sha256',identity)!=identity:
                raise ValueError('Offline encoding hash mismatch')
            encoding=offline_encoding(raw)
            result.update(input_estimate=len(encoding.encode(text,disallowed_special=())),
                          estimator='offline_tiktoken',tokenizer_sha256=identity)
        except (ImportError,OSError,ValueError,KeyError,TypeError) as error:
            result['fallback_reason']=type(error).__name__
    if policy.get('require_local_tokenizer') and result['estimator']!='offline_tiktoken':
        from .core import PolicyDenied
        raise PolicyDenied('Required offline tokenizer unavailable: '+result.get('fallback_reason','not configured'))
    return result


@lru_cache(maxsize=1)
def offline_encoding(raw):
    import tiktoken
    data=json.loads(raw)
    ranks={base64.b64decode(k,validate=True):v for k,v in data['mergeable_ranks'].items()}
    return tiktoken.Encoding(name=data['name'],pat_str=data['pat_str'],
                            mergeable_ranks=ranks,special_tokens=data['special_tokens'])


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
    report.update(actual_tokens_spent=budget.tokens, total_token_limit=budget.limits.max_tokens,
                  total_tokens_remaining=budget.limits.max_tokens-budget.tokens,
                  model_calls_spent=budget.model_calls, model_call_limit=budget.limits.max_model_calls,
                  wallclock_remaining=budget.remaining)
    constraints=[]
    if budget.tokens >= budget.limits.max_tokens: constraints.append('global_tokens_spent')
    if budget.model_calls >= budget.limits.max_model_calls: constraints.append('global_model_calls_spent')
    if reserved>remaining: constraints.append('global_next_request_reservation')
    if reserved>model_available: constraints.append('model_context_window')
    if reserved>per_call_available: constraints.append('configured_per_call_input')
    report['binding_constraints']=constraints
    if constraints:
        from .guard_recovery import GuardIncident
        terminal=any(c.endswith('_spent') for c in constraints)
        incident=GuardIncident('token_admission_rejected', 'authorized_budget' if terminal else 'request_capacity',
            'fit_request_without_expanding_total_budget_or_dropping_required_evidence',
            () if terminal else ('lossless_repack', 'reselect_evidence', 'checkpoint_stop'), report)
        error=(BudgetExceeded('Insufficient remaining token budget for proposal input, safety and output')
               if terminal else
               InputCapacityExceeded('Next proposal request does not fit remaining token reservation'
                   if 'global_next_request_reservation' in constraints else
                   'Proposal exceeds configured model/per-call input token capacity'))
        error.context_metrics=report
        error.guard_incident=incident.record()
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


def compact_json_payloads(messages):
    """Remove JSON layout only, preserving source/log string values and all messages."""
    result=[]
    for message in messages:
        view=dict(message)
        if view.get('role') == 'user' and isinstance(view.get('content'), str):
            try:
                data=json.loads(view['content'])
            except (ValueError, TypeError):
                data=None
            if isinstance(data, (dict, list)):
                view['content']=json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        result.append(view)
    return result


def admission_with_recovery(messages, schema, policy, output, budget, *, repack=None, on_event=None):
    """At most two deterministic, host-owned repacks. No dispatch, new budget or truncation."""
    try:
        return messages, admission(messages, schema, policy, output, budget)
    except BudgetExceeded as first:
        if not policy.get('recover_capacity') or not hasattr(first, 'context_metrics'):
            raise
        current=messages; last=first
    def signature(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()
    seen={signature(current)}
    for name, operation in (('json_layout', compact_json_payloads), ('registered_evidence_repack', repack)):
        incident=last.guard_incident
        if not incident['allowed_actions']:
            if on_event: on_event({'incident':incident, 'disposition':'checkpoint_stop', 'request_sha256':signature(current)})
            raise last
        budget.check()
        if operation is None:
            continue
        proposed=operation(current)
        fingerprint=signature(proposed)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        event={'incident':incident, 'disposition':'repack_then_revalidate', 'operation':name,
               'request_sha256':signature(current), 'candidate_request_sha256':fingerprint}
        if on_event: on_event(event)
        try:
            metrics=admission(proposed, schema, policy, output, budget)
        except BudgetExceeded as error:
            if not hasattr(error, 'context_metrics'): raise
            last=error
            current=proposed
        else:
            if on_event: on_event({'incident':incident, 'disposition':'recovered', 'operation':name,
                                   'request_sha256':fingerprint, 'metrics':metrics})
            return proposed, metrics
    if on_event: on_event({'incident':last.guard_incident, 'disposition':'checkpoint_stop', 'request_sha256':signature(current)})
    raise last


def reserve_role_call(workspace, messages, schema, settings, output, *, role, stage, legacy_size):
    """Shared policy-based reservation for Scout/Critic; no role receives a fresh budget."""
    policy=settings.get('proposal_context_policy')
    if policy is None:
        workspace.budget.allow_model(legacy_size, output)
        return messages, None
    original=messages
    def event(record):
        fact=workspace.ledger.add('decision',role,'Role token admission guard',
                                 {'stage':stage,'event':record,'messages':original,'schema':schema})
        workspace.trace.emit(role,'role_capacity_guard',stage=stage,fact_id=fact,**record)
    try:
        packed,metrics=admission_with_recovery(messages,schema,policy,output,workspace.budget,on_event=event)
    except BudgetExceeded as error:
        event({'disposition':'checkpoint_stop','incident':getattr(error,'guard_incident',None)})
        raise
    workspace.budget.allow_model(metrics['reserved_input_tokens'],output)
    workspace.trace.emit(role,'role_token_admitted',stage=stage,**metrics)
    return packed,metrics


def observe_role_usage(workspace, reply, metrics, *, role, stage):
    if metrics is None or not isinstance(getattr(reply,'metadata',None),dict):return
    actual=reply.metadata.get('prompt_tokens')
    if type(actual) is int and actual>=0:
        workspace.trace.emit(role,'role_token_estimate_observed',stage=stage,
            estimated_input_tokens=metrics['input_estimate'],actual_input_tokens=actual,
            reserved_input_tokens=metrics['reserved_input_tokens'],estimator=metrics['estimator'],
            tokenizer_sha256=metrics.get('tokenizer_sha256'),policy_sha256=metrics['policy_sha256'])
