"""Offline inventory of possible Scout supervision; never approves training data."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time

from compass.progress import atomic_json, ProgressLog


SKIP_DIRECTORIES={'.git','.venv','venv','site-packages','node_modules','snapshot',
    'repo','solver-repo','snapshot-base','snapshot-gold','base','gold','datasets','__pycache__'}


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,
                                     separators=(',',':')).encode('utf-8')).hexdigest()


def _linked(path):
    return path.is_symlink() or bool(getattr(path.lstat(),'st_file_attributes',0)&1024)


def _hash(path,check):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            check();chunk=stream.read(1048576)
            if not chunk:break
            value.update(chunk)
    return value.hexdigest()


def _context(path,check):
    """Only bounded, adjacent run metadata. Never load task answers or source code."""
    result={'instance_id':None,'runtime_status':None,'official_resolved':None,
            'manual_assistance':'unknown','repository':'unknown','metadata':None}
    for parent in list(path.parents)[:3]:
        check();metadata=parent/'trial.json'
        if not metadata.is_file() or _linked(metadata):continue
        if metadata.stat().st_size>2097152:
            result['metadata_issue']='metadata_too_large';return result
        before=_hash(metadata,check)
        try:value=json.loads(metadata.read_text(encoding='utf-8'))
        except (ValueError,UnicodeError):
            result['metadata_issue']='invalid_metadata';return result
        if not isinstance(value,dict):
            result['metadata_issue']='invalid_metadata';return result
        if _hash(metadata,check)!=before:raise ValueError('Adjacent metadata changed during audit')
        result.update(instance_id=value.get('instance_id'),runtime_status=value.get('runtime_status'),
            official_resolved=value.get('official_resolved'),
            continuation=bool(value.get('continuation')),
            diagnostic_report_present=bool((value.get('continuation') or {}).get('diagnostic_report_sha256'))
                if isinstance(value.get('continuation'),dict) else False,
            metadata={'path':str(metadata),'sha256':before})
        # A canonical repository is not reliably recoverable from an instance ID.
        return result
    return result


def _selection(request,response):
    kwargs=request.get('kwargs',{})
    if not isinstance(kwargs,dict):return None
    schema=kwargs.get('schema')
    if not isinstance(schema,dict):return None
    properties=schema.get('properties',{})
    if not isinstance(properties,dict) or set(properties) not in ({'files'},{'locations'}):return None
    field=next(iter(properties));spec=properties[field]
    if not isinstance(spec,dict):return None
    args=request.get('args',[])
    messages=args[0] if isinstance(args,list) and args else kwargs.get('messages')
    if not isinstance(messages,list) or not messages:
        return {'kind':field,'issues':['missing_messages']}
    if any(not isinstance(m,dict) or not isinstance(m.get('role'),str) or not isinstance(m.get('content'),str)
           for m in messages):return {'kind':field,'issues':['unsupported_messages']}
    content=response.get('content')
    try:value=json.loads(content) if isinstance(content,str) else None
    except ValueError:value=None
    issues=[];items=spec.get('items',{})
    if schema.get('type')!='object' or spec.get('type')!='array' or not isinstance(items,dict):
        return {'kind':field,'issues':['unsupported_schema']}
    if any(type(spec[k]) is not int or spec[k]<0 for k in ('minItems','maxItems') if k in spec):
        return {'kind':field,'issues':['unsupported_schema']}
    if 'enum' in items and not isinstance(items['enum'],list):
        return {'kind':field,'issues':['unsupported_schema']}
    if not isinstance(value,dict) or set(value)!={field} or not isinstance(value.get(field),list):
        issues.append('invalid_selection_shape');selected=[]
    else:
        selected=value[field]
        if len(selected)<spec.get('minItems',0) or len(selected)>spec.get('maxItems',len(selected)):
            issues.append('selection_count_outside_schema')
        item_type=items.get('type') if isinstance(items,dict) else None
        if item_type not in ('integer','string'):issues.append('unsupported_item_type')
        elif any((type(v) is not int if item_type=='integer' else not isinstance(v,str)) for v in selected):
            issues.append('invalid_item_type')
        if 'enum' in items and any(v not in items['enum'] for v in selected):
            issues.append('selection_outside_schema_enum')
        if spec.get('uniqueItems') and len({_digest(v) for v in selected})!=len(selected):
            issues.append('duplicate_selection')
    return {'kind':field,'issues':issues,'selected_count':len(selected),
        'empty_selection':not selected,'enum_bound':isinstance(items,dict) and isinstance(items.get('enum'),list),
        'message_characters':sum(len(m['content']) for m in messages),
        'state_sha256':_digest({'messages':messages,'schema':schema}),
        'target_sha256':_digest(value),'example_sha256':_digest({'messages':messages,'schema':schema,'target':value})}


def _inspect(path,check,max_file_bytes,max_line_bytes):
    inventory={'path':str(path),'sha256':None,'bytes':path.stat().st_size,
               'status':'inspected','events':{},'issues':[]}
    if inventory['bytes']>max_file_bytes:
        inventory.update(status='excluded',issues=['file_resource_envelope_exceeded']);return inventory,[]
    before=_hash(path,check);inventory['sha256']=before
    context=_context(path,check);inventory['context']=context
    pending=None;rows=[];events=Counter()
    with path.open('rb') as stream:
        number=0
        while True:
            check();line=stream.readline(max_line_bytes+1)
            if not line:break
            number+=1
            if len(line)>max_line_bytes:
                inventory.update(status='excluded',issues=['line_resource_envelope_exceeded']);rows=[];break
            try:event=json.loads(line)
            except (ValueError,UnicodeError):
                inventory['issues'].append({'line':number,'reason':'invalid_json_event'})
                # Lost event boundaries must not silently associate later output.
                pending=None;continue
            if not isinstance(event,dict) or not isinstance(event.get('event'),str):
                inventory['issues'].append({'line':number,'reason':'unsupported_event'});pending=None;continue
            kind=event['event'];events[kind]+=1
            if kind=='request':
                if pending:inventory['issues'].append({'line':pending[0],'reason':'request_without_terminal_event'})
                pending=(number,event)
            elif kind in ('response','error'):
                if pending is None:
                    inventory['issues'].append({'line':number,'reason':'orphan_terminal_event'});continue
                first,request=pending;pending=None
                if kind=='error':continue
                selection=_selection(request,event)
                if selection is None:continue
                rows.append({'transcript':str(path),'transcript_sha256':before,
                    'request_line':first,'response_line':number,'context':context,**selection,
                    'training_approved':False,'role_attribution':'schema_inferred_needs_review',
                    'quality':'structural_screen_only_not_semantic_label',
                    'review_required':['semantic_relevance','readable_vs_writable_scope','human_assistance',
                                       'reference_answer_contamination','repository_and_task_split']})
    if pending:inventory['issues'].append({'line':pending[0],'reason':'request_without_terminal_event'})
    inventory['events']=dict(events)
    if _hash(path,check)!=before:
        inventory.update(status='excluded',issues=['transcript_changed_during_audit']);rows=[]
    # Malformed/event-loss files remain inventory evidence, not candidate examples.
    if inventory['issues']:
        inventory['status']='excluded';rows=[]
    return inventory,rows


def audit(roots,output,*,timeout=120,max_file_bytes=33554432,max_line_bytes=2097152):
    """Write metadata-only review candidates; no raw prompts/targets or SFT export."""
    if type(timeout) is not int or not 1<=timeout<=1800:raise ValueError('Audit deadline must be1..1800seconds')
    if min(max_file_bytes,max_line_bytes)<=0:raise ValueError('Positive file/line envelopes required')
    paths=[]
    for root in roots:
        root=Path(root)
        if _linked(root) or not root.is_dir():raise ValueError('Require real transcript evidence directories')
        paths.append(root.resolve())
    if not paths:raise ValueError('At least one evidence root is required')
    output=Path(output).resolve()
    if any(output==p or output.is_relative_to(p) for p in paths):
        raise ValueError('Audit output must be outside evidence roots')
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    report={'schema_version':1,'status':'running','model_calls':0,'training_approved':0,
        'roots':[str(p) for p in paths],'files':[],'limits':{'timeout_seconds':timeout,
            'max_file_bytes':max_file_bytes,'max_line_bytes':max_line_bytes},
        'scan_policy':{'filenames':'*transcript.jsonl','excluded_directories':sorted(SKIP_DIRECTORIES),
                       'symlinks_and_reparse_points':'excluded'},
        'scope':'Offline metadata inventory. Schema-inferred Scout candidates require review; no data splits, training, semantic correctness or contamination certification.'}
    from .evaluation_protocol import implementation_hashes
    report['implementation']=implementation_hashes(Path(__file__).resolve().parents[1])
    def check():
        if time.monotonic()-started>=timeout:raise TimeoutError('Shared Scout audit deadline exceeded')
    def save():
        report['seconds']=round(time.monotonic()-started,3);atomic_json(output/'report.json',report)
    save();files=set();duplicates=set();counts=Counter();tasks=Counter();states={}
    with ProgressLog(output/'progress.jsonl',console=True) as progress:
        def emit(event,**fields):
            try:progress.emit(event,**fields)
            except OSError:report['telemetry_error']=True
        try:
            emit('scan',roots=len(paths))
            for root in paths:
                for directory,children,names in os.walk(root,onerror=lambda error:(_ for _ in ()).throw(error)):
                    check();parent=Path(directory)
                    children[:]=[n for n in children if n not in SKIP_DIRECTORIES and not n.startswith('harness-') and not _linked(parent/n)]
                    for name in names:
                        if name.endswith('transcript.jsonl'):
                            path=parent/name
                            if not _linked(path):files.add(path.resolve())
            report['discovered_transcripts']=len(files);save()
            with (output/'candidates.jsonl').open('x',encoding='utf-8',newline='\n') as stream:
                for path in sorted(files):
                    check();emit('inspect',completed=len(report['files']),total=len(files))
                    inventory,rows=_inspect(path,check,max_file_bytes,max_line_bytes)
                    report['files'].append(inventory)
                    for row in rows:
                        if row['issues']:
                            counts['structurally_rejected']+=1
                        else:
                            counts['structurally_screened']+=1
                            key=row['example_sha256'];row['exact_duplicate']=key in duplicates
                            if key in duplicates:counts['exact_duplicates']+=1
                            else:
                                duplicates.add(key);counts['unique_review_candidates']+=1
                                task=row['context'].get('instance_id') or 'unknown'
                                tasks[task]+=1
                                states.setdefault(row['state_sha256'],set()).add(row['target_sha256'])
                        counts['selection_responses']+=1;counts[row['kind']]+=1
                        stream.write(json.dumps(row,ensure_ascii=False)+'\n')
                    stream.flush();save()
                os.fsync(stream.fileno())
            # A source inspected early must not change while later files are read.
            for entry in report['files']:
                if entry.get('sha256') and _hash(Path(entry['path']),check)!=entry['sha256']:
                    raise ValueError('Transcript changed before audit publication')
                metadata=entry.get('context',{}).get('metadata')
                if metadata and _hash(Path(metadata['path']),check)!=metadata['sha256']:
                    raise ValueError('Run metadata changed before audit publication')
            report['status']='completed'
        except (TimeoutError,OSError,ValueError) as error:
            report.update(status='incomplete',error_type=type(error).__name__)
        finally:
            report['counts']=dict(counts);report['unique_candidates_by_task']=dict(tasks)
            report['states_with_different_targets']=sum(len(v)>1 for v in states.values())
            report['excluded_transcripts']=sum(f['status']=='excluded' for f in report['files'])
            candidates=output/'candidates.jsonl'
            if candidates.is_file():report['candidates_sha256']=_hash(candidates,lambda:None)
            save()
    return report
