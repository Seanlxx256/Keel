"""Three frozen role requests under one strict counting budget; no repair or Docker."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from compass.progress import atomic_json
from keel.core import Budget,Limits,Ledger,Trace,ModelError
from keel.context_budget import reserve_role_call,observe_role_usage,validate_policy,estimate_input
from keel.evaluation_protocol import file_hash
from keel.models import from_config
from keel.recovery import validate_critic_decision
from keel.runtime_snapshot import verify_snapshot


def validate_reply(value,request):
    role=request['role'];schema=request['schema']
    if role=='critic':return validate_critic_decision(value)
    if not isinstance(value,dict) or set(value)!=set(schema['required']):raise ValueError('Role response fields mismatch')
    if role=='scout':
        files=value['files'];allowed=schema['properties']['files']['items']['enum']
        if (not isinstance(files,list) or not 1<=len(files)<=8 or len(set(files))!=len(files)
                or any(not isinstance(p,str) or p not in allowed for p in files)):
            raise ValueError('Scout selection outside frozen catalog')
    elif role=='implementer':
        allowed=schema['properties']['edits']['items']['properties']['path']['enum']
        if not isinstance(value['summary'],str) or not isinstance(value['edits'],list) or not 1<=len(value['edits'])<=8:
            raise ValueError('Invalid proposal shape')
        for edit in value['edits']:
            if (not isinstance(edit,dict) or set(edit)!={'path','old','new'}
                    or any(not isinstance(edit[k],str) for k in edit)
                    or edit['path'] not in allowed or not edit['old']):raise ValueError('Invalid scoped edit shape')
    else:raise ValueError('Unknown role')
    return value


def execute(plan_path,*,model=None,resume=False):
    plan_path=Path(plan_path);plan=json.loads(plan_path.read_text(encoding='utf-8'));identity=file_hash(plan_path)
    if plan_path.with_suffix('.sha256').read_text().strip()!=identity:raise ValueError('Plan identity mismatch')
    verify_snapshot(plan['snapshot'])
    for source,expected in plan['frozen_files'].items():
        if file_hash(Path(source))!=expected:raise ValueError('Frozen input drift')
    policy=json.loads(Path(plan['policy']).read_text(encoding='utf-8'));validate_policy(policy)
    if not policy.get('require_local_tokenizer'):raise ValueError('Live check requires strict offline counting')
    estimate_input([],{},policy)
    requests=json.loads(Path(plan['requests']).read_text(encoding='utf-8'))
    if [r['role'] for r in requests]!=['critic','scout','implementer']:raise ValueError('Expected three fixed role calls')
    for request in requests:
        if type(request['max_output']) is not int or not 1<=request['max_output']<=4096:
            raise ValueError('Invalid fixed output allowance')
    for request in requests:
        size=len(json.dumps(request['messages'],ensure_ascii=False).encode())+len(json.dumps(request['schema']).encode())
        if size>policy['max_request_bytes']:raise ValueError('Frozen request exceeds byte ceiling')
    budget=Budget(Limits(max_wallclock=180,max_model_calls=3,max_tokens=45000,max_tool_calls=1))
    output=Path(plan['output'])
    if not output.resolve().is_relative_to(plan_path.parent.resolve()):
        raise ValueError('Check output must stay within the experiment directory')
    if model is None:model=from_config(json.loads(Path(plan['model_config']).read_text(encoding='utf-8')))
    need_dispatch=not resume or any(not (output/(r['role']+'.json')).exists() for r in requests)
    if need_dispatch and hasattr(model,'check_credentials'):model.check_credentials()
    if resume:
        previous=json.loads((output/'report.json').read_text(encoding='utf-8'))
        if previous['plan_sha256']!=identity:raise ValueError('Resume plan mismatch')
        for key in ('tokens','model_calls','tool_calls'):setattr(budget,key,previous['budget'][key])
        budget.started-=previous['budget']['wallclock_seconds']
    else:output.mkdir(parents=True,exist_ok=False)
    ledger=Ledger(output/'ledger.sqlite');ws=SimpleNamespace(budget=budget,ledger=ledger,trace=Trace(output/'trace.jsonl'))
    report={'status':'running','plan_sha256':identity,'roles':[],
            'scope':'Frozen request/counting interface check only; no patch application, semantic diagnosis score or acceptance.'}
    def save():report['budget']=budget.report();atomic_json(output/'report.json',report)
    save()
    try:
        for request in requests:
            role=request['role'];path=output/(role+'.json');receipt=output/(role+'-receipt.json')
            if path.exists():
                if (not receipt.exists() or json.loads(receipt.read_text(encoding='utf-8'))!={'sha256':file_hash(path)}):
                    raise ValueError('Unfinished role retained; no automatic paid retry')
                record=json.loads(path.read_text(encoding='utf-8'))
                if record['status']!='completed':raise ValueError('Incomplete role cannot be retried')
                if record['budget']['model_calls']>budget.model_calls:
                    for key in ('tokens','model_calls','tool_calls'):setattr(budget,key,record['budget'][key])
                    budget.started-=max(0,record['budget']['wallclock_seconds']-budget.report()['wallclock_seconds'])
            else:
                record={'status':'pending','role':role};atomic_json(path,record)
                messages,metrics=reserve_role_call(ws,request['messages'],request['schema'],
                    {'proposal_context_policy':policy},request['max_output'],role=role,stage='frozen-live-check',legacy_size=0)
                record.update(status='dispatched',admission=metrics,budget=budget.report());atomic_json(path,record);save()
                print('[Role token check] '+role+'; <=60s; offline_tiktoken',flush=True)
                try:
                    reply=model.complete_json(messages,schema=request['schema'],timeout=min(60,budget.remaining),max_output=request['max_output'])
                except ModelError as error:
                    if error.tokens is not None:budget.charge_tokens(error.tokens)
                    record.update(status='incomplete',error_type=type(error).__name__,budget=budget.report(),
                                  diagnostics=getattr(error,'diagnostics',None),raw_response=getattr(error,'content',None))
                    atomic_json(path,record);raise
                record.update(raw_response=reply.content,metadata=reply.metadata)
                atomic_json(path,record)
                budget.charge_tokens(reply.tokens if reply.tokens is not None else metrics['reserved_input_tokens']+request['max_output'])
                observe_role_usage(ws,reply,metrics,role=role,stage='frozen-live-check')
                validate_reply(json.loads(reply.content),request)
                budget.check();record.update(status='completed',budget=budget.report());atomic_json(path,record)
                atomic_json(receipt,{'sha256':file_hash(path)})
            report['roles'].append({'role':role,'status':record['status'],'admission':record['admission'],
                                    'actual_prompt_tokens':(record.get('metadata') or {}).get('prompt_tokens')});save()
        report['status']='completed'
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__);raise
    finally:save();ledger.close()
    return report
