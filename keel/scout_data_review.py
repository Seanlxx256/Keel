"""Evidence-bound contract review of Scout candidates, not semantic approval."""
from collections import Counter
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import time

from compass.progress import atomic_json, ProgressLog
from .audit import protected_path
from .scout_data_audit import _digest, _hash, _linked, _selection


def load_event_pair(path,request_line,response_line,max_line_bytes,check):
    if type(request_line) is not int or type(response_line) is not int or not 0<request_line<response_line:
        raise ValueError('Invalid source event positions')
    needed={request_line,response_line};events={}
    with Path(path).open('rb') as stream:
        for number in range(1,response_line+1):
            check();line=stream.readline(max_line_bytes+1)
            if not line or len(line)>max_line_bytes:raise ValueError('Transcript framing changed')
            if number in needed:events[number]=json.loads(line)
    request,response=events[request_line],events[response_line]
    if request.get('event')!='request' or response.get('event')!='response':raise ValueError('Event pair mismatch')
    return request,response


def inspect_selection(request,response,context):
    screened=_selection(request,response)
    if screened is None:raise ValueError('Not a Scout selection schema')
    invalid=list(screened['issues']);notes=[]
    field=screened['kind'];kwargs=request.get('kwargs',{})
    args=request.get('args',[]);messages=args[0] if isinstance(args,list) and args else kwargs.get('messages')
    try:data=json.loads(messages[-1]['content'])
    except (ValueError,KeyError,TypeError,IndexError):data=None
    result={'kind':field,'violations':invalid,'notes':notes,'training_approved':False,
        'input_fields':sorted(data) if isinstance(data,dict) else [],
        'scope':'Original input catalog plus current lexical write protections; no live workspace/symlink or semantic proof'}
    if not isinstance(data,dict):
        result['decision']='hold_unsupported_input';return result
    try:selected=json.loads(response['content'])[field]
    except (ValueError,KeyError,TypeError):selected=[]
    if not isinstance(selected,list) or any(not isinstance(v,str) for v in selected):
        result['decision']='exclude_current_contract';return result
    page='catalog_page' in data
    if field=='files':
        catalog=data.get('paths');allowed=set(catalog) if isinstance(catalog,list) and all(isinstance(v,str) for v in catalog) else None
        names=selected
    else:
        allowed=set();names=[];symbols={}
        structure=data.get('structure')
        if not isinstance(structure,list):allowed=None
        else:
            for row in structure:
                if not isinstance(row,dict) or not isinstance(row.get('path'),str):
                    allowed=None;break
                for symbol in row.get('symbols',[]):
                    if isinstance(symbol,list) and len(symbol)>=2 and type(symbol[0]) is int:
                        key=f"{row['path']}:{symbol[0]}";allowed.add(key);symbols[key]=symbol[1]
            result['selected_symbols']=[{'id':v,'name':symbols.get(v)} for v in selected]
        for item in selected:
            name,separator,line=item.rpartition(':')
            if not separator or not line.isdigit() or int(line)<=0:
                invalid.append('invalid_location_identifier')
            else:names.append(name)
    if page and allowed is not None:
        previous=data.get('previous_selection',[])
        if isinstance(previous,list) and all(isinstance(v,str) for v in previous):allowed.update(previous)
        else:allowed=None
    result['stage']=('file_catalog_page' if page else 'file_selection') if field=='files' else (
        'symbol_catalog_page' if page else 'symbol_selection')
    if allowed is None:notes.append('catalog_unavailable')
    else:
        outside=[v for v in selected if v not in allowed]
        if outside:invalid.append('identifier_not_displayed_in_input_catalog')
        result['outside_catalog']=outside
    for name in names:
        if (not name or PurePosixPath(name).is_absolute() or PureWindowsPath(name).drive
                or '..' in PurePosixPath(name.replace('\\','/')).parts):
            invalid.append('unsafe_relative_path')
        elif protected_path(name):invalid.append('current_protected_write_target')
    result['selected_paths']=names
    goal=data.get('goal','')
    embedded_feedback=isinstance(goal,str) and 'Observed failed verification (untrusted data):' in goal
    result['paths_mentioned_in_goal']=[name for name in names if isinstance(goal,str) and name in goal]
    if not selected:
        if page:
            system=' '.join(m.get('content','') for m in messages if m.get('role')=='system').lower()
            notes.append('explicit_empty_means_retain' if 'empty array means no update' in system
                         else 'historical_empty_page_semantics_unverified')
        else:invalid.append('empty_nonpaged_selection')
    if page:notes.append('page_choice_is_not_final_global_localization')
    if context.get('continuation'):notes.append('saved_source_continuation_requires_provenance_review')
    if context.get('diagnostic_report_present'):notes.append('historical_diagnostic_report_requires_provenance_review')
    if embedded_feedback:notes.append('embedded_verification_feedback_requires_source_version_review')
    if data.get('verification_errors'):notes.append('verification_feedback_is_present_not_automatically_leakage')
    result['violations']=sorted(set(invalid));result['notes']=sorted(set(notes))
    if invalid:result['decision']='exclude_current_contract'
    elif allowed is None:result['decision']='hold_unsupported_input'
    elif context.get('continuation') or context.get('diagnostic_report_present') or embedded_feedback:
        result['decision']='hold_provenance_review'
    else:result['decision']='needs_semantic_review'
    return result


def review(audit_dir,queue_path,output,*,timeout=120):
    if type(timeout) is not int or not 1<=timeout<=1800:raise ValueError('Review deadline1..1800seconds')
    audit_dir,queue_path,output=map(lambda p:Path(p).resolve(),(audit_dir,queue_path,output))
    started=time.monotonic()
    def check():
        if time.monotonic()-started>=timeout:raise TimeoutError('Scout review deadline exceeded')
    source=audit_dir/'report.json';candidates=audit_dir/'candidates.jsonl'
    report_hash=_hash(source,check);candidate_hash=_hash(candidates,check);queue_hash=_hash(queue_path,check)
    report=json.loads(source.read_text(encoding='utf-8'));queue=json.loads(queue_path.read_text(encoding='utf-8'))
    if (report['status']!='completed' or candidate_hash!=report['candidates_sha256']
            or queue['source_report_sha256']!=report_hash or queue['source_candidates_sha256']!=candidate_hash):
        raise ValueError('Audit/queue identity changed')
    candidate_rows={}
    with candidates.open(encoding='utf-8') as stream:
        for line in stream:
            check();row=json.loads(line)
            key=(row['transcript'],row['request_line'],row['response_line']);candidate_rows[key]=row
    selected=[];seen=set();hashes={str(source):report_hash,str(candidates):candidate_hash,str(queue_path):queue_hash}
    for item in queue['items']:
        check();key=(item['transcript'],item['request_line'],item['response_line'])
        if key in seen or key not in candidate_rows:raise ValueError('Queue contains duplicate or unknown sample')
        row=candidate_rows[key];seen.add(key)
        if (item['transcript_sha256']!=row['transcript_sha256'] or item['kind']!=row['kind']
                or item['instance_id']!=row['context']['instance_id']):raise ValueError('Queue provenance mismatch')
        path=Path(row['transcript'])
        if _linked(path) or not any(path.resolve().is_relative_to(Path(p)) for p in report['roots']):
            raise ValueError('Transcript outside audit roots or linked')
        hashes[str(path)]=row['transcript_sha256']
        metadata=row['context'].get('metadata')
        if metadata:hashes[metadata['path']]=metadata['sha256']
        selected.append(row)
    output.mkdir(parents=True,exist_ok=False)
    result={'schema_version':1,'status':'running','model_calls':0,'training_approved':0,'inputs':hashes,'items':[],
        'reviewer':'deterministic_contract_review','scope':'Contract/provenance triage, not semantic labels, reference-free certification or SFT export'}
    def save():
        result['seconds']=round(time.monotonic()-started,3);atomic_json(output/'review.json',result)
    save()
    try:
        for name,expected in hashes.items():
            if _hash(Path(name),check)!=expected:raise ValueError('Review source changed')
        with ProgressLog(output/'progress.jsonl',console=True) as progress:
            for row in selected:
                check()
                try:progress.emit('review',completed=len(result['items']),total=len(selected))
                except OSError:result['telemetry_error']=True
                request,response=load_event_pair(row['transcript'],row['request_line'],row['response_line'],
                    report['limits']['max_line_bytes'],check)
                screened=_selection(request,response)
                if screened is None:raise ValueError('Selection schema changed')
                for key in ('state_sha256','target_sha256','example_sha256'):
                    if row.get(key)!=screened.get(key):raise ValueError('Sample identity mismatch')
                item=inspect_selection(request,response,row['context'])
                item.update(sample_id=_digest([row['transcript_sha256'],row['request_line'],row['response_line']]),
                    transcript=row['transcript'],request_line=row['request_line'],response_line=row['response_line'],
                    instance_id=row['context']['instance_id'],example_sha256=row.get('example_sha256'))
                result['items'].append(item);save()
        for name,expected in hashes.items():
            if _hash(Path(name),check)!=expected:raise ValueError('Review input changed before publication')
        result['status']='completed'
    except (OSError,ValueError,TimeoutError) as error:
        result.update(status='incomplete',error_type=type(error).__name__)
    finally:
        result['counts']=dict(Counter(item['decision'] for item in result['items']));save()
    return result
