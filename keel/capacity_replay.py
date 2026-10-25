"""Offline capacity measurements for recorded dispatched proposal requests only."""
import hashlib
import json
import time
from pathlib import Path
from compass.progress import atomic_json
from keel.context_budget import estimate_input
from keel.proposals import repack_proposal_messages


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def measure_request(messages, schema, policy=None):
    packed=repack_proposal_messages(messages)
    before=json.loads(messages[1]['content']);after=json.loads(packed[1]['content'])
    critical_before={k:v for k,v in before.items() if k!='goal'}
    critical_after={k:v for k,v in after.items() if k!='goal'}
    if critical_before!=critical_after or packed[0]!=messages[0] or len(packed)!=len(messages):
        raise ValueError('Repacking changed non-goal evidence or instructions')
    # The same registered operation is used in production; counts are conservative bytes, not exact provider tokens.
    original=estimate_input(messages,schema,policy or {})
    compacted=estimate_input(packed,schema,policy or {})
    return {'request_sha256':fingerprint(messages),'repacked_sha256':fingerprint(packed),
            'schema_sha256':fingerprint(schema),'original_input_estimate':original['input_estimate'],
            'repacked_input_estimate':compacted['input_estimate'],
            'saved_estimated_units':original['input_estimate']-compacted['input_estimate'],
            'estimator':original['estimator'],'tokenizer_sha256':original.get('tokenizer_sha256'),'provider_exact':False,
            'non_goal_payload_sha256':fingerprint(critical_before),'non_goal_payload_unchanged':True,
            'goal_changed':before['goal']!=after['goal']}


def replay(paths, output, *, timeout=60, policy=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    deadline=time.monotonic()+timeout
    root=Path(__file__).resolve().parents[1]
    report={'implementation':{name:hashlib.sha256((root/name).read_bytes()).hexdigest()
              for name in ('keel/capacity_replay.py','keel/context_budget.py','keel/proposals.py')},'status':'running','policy':policy,'provider_calls':0,'records':[],'inputs':[],
            'scope':'Recorded dispatched proposal requests, not reconstruction of rejected requests or acceptance.'}
    try:
        for source in paths:
            path=Path(source)
            if time.monotonic()>=deadline:raise TimeoutError('Offline replay deadline')
            if path.stat().st_size>64000000:raise ValueError('Transcript exceeds replay read envelope')
            raw=path.read_bytes()
            report['inputs'].append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()})
            print('[Capacity replay] '+path.parent.name,flush=True)
            lines=raw.splitlines()
            for index,line in enumerate(lines):
                if time.monotonic()>=deadline:raise TimeoutError('Offline replay deadline')
                row=json.loads(line)
                messages=(row.get('args') or [None])[0] if 'args' in row else row.get('messages')
                settings=row.get('kwargs',row.get('settings',{}))
                schema=settings.get('schema',{})
                if not isinstance(messages,list) or 'edits' not in schema.get('required',[]):continue
                result=measure_request(messages,schema,policy)
                result.update(source=str(path),line=index+1,output_allowance=settings.get('max_output'))
                # Pair only the immediately following successful response, never infer missing usage.
                following=json.loads(lines[index+1]) if index+1<len(lines) else {}
                if following.get('event')=='response':
                    metadata=following.get('metadata') or {}
                    total=following.get('tokens'); actual=metadata.get('prompt_tokens')
                    if type(total) is int and total>=0:
                        result['observed_total_tokens']=total
                        result['usage_scope']='Reported total includes output; it is only an upper bound on input.'
                    if type(actual) is int and actual>=0:
                        result['observed_input_tokens']=actual
                        result['input_estimate_over_actual']=result['original_input_estimate']/actual if actual else None
                report['records'].append(result)
            atomic_json(output/'report.json',report)
        report.update(status='completed' if report['records'] else 'no_supported_requests',requests=len(report['records']),
                      changed_requests=sum(r['saved_estimated_units']>0 for r in report['records']),
                      saved_estimated_units=sum(r['saved_estimated_units'] for r in report['records']))
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__)
        raise
    finally:atomic_json(output/'report.json',report)
    atomic_json(output/'receipt.json',{'report_sha256':hashlib.sha256((output/'report.json').read_bytes()).hexdigest()})
    return report
