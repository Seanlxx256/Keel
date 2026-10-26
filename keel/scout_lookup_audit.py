"""Offline lookup error audit; secondary format recovery never changes raw scores."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time

from compass.progress import atomic_json, ProgressLog
from .scout_candidate_ids import decode_ids, lookup_example, single_json_fence
from .scout_tokenizer import file_hash


def canonical_candidate_ids(text, mapping, spec):
    """Target-independent proposal: one JSON fence and canonical decimal strings.

    No scalar wrapping, partial extraction, extra-key removal, pruning, deduping,
    nearest-ID matching or guessing. The ordinary strict decoder checks the result.
    This opt-in offline analysis is not installed into the production runtime.
    """
    unwrapped=single_json_fence(text);changes=[]
    if unwrapped!=text:changes.append('single_json_fence')
    def unique_object(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('Duplicate JSON key')
            value[key]=item
        return value
    value=json.loads(unwrapped,object_pairs_hook=unique_object)
    if not isinstance(value,dict) or set(value)!={'candidate_ids'} or not isinstance(value['candidate_ids'],list):
        raise ValueError('Expected candidate_ids object')
    ids=[]
    for item in value['candidate_ids']:
        if isinstance(item,str):
            if len(item)>len(str(max(0,len(mapping)-1))) or re.fullmatch(r'0|[1-9][0-9]*',item) is None:
                raise ValueError('Noncanonical integer string')
            item=int(item)
            if 'decimal_string_to_integer' not in changes:changes.append('decimal_string_to_integer')
        ids.append(item)
    canonical=json.dumps({'candidate_ids':ids})
    decode_ids(canonical,mapping,spec)
    return canonical,changes


def assess_output(text,mapping,spec,expected_id,finish_reason):
    """Keep exact-match truth out of normalization; use it only for scoring."""
    if type(expected_id) is not int or not 0<=expected_id<len(mapping):raise ValueError('Invalid lookup truth')
    result={'strict_valid':False,'strict_exact':False,'normalized_valid':False,'normalized_exact':False,
            'format_changes':[],'censored':finish_reason!='eos','training_allowed':False}
    expected=[mapping[expected_id]]
    try:
        strict=json.loads(decode_ids(text,mapping,spec))['locations']
        result.update(strict_valid=True,strict_exact=strict==expected)
    except ValueError:pass
    try:
        canonical,changes=canonical_candidate_ids(text,mapping,spec)
        selected=json.loads(decode_ids(canonical,mapping,spec))['locations']
        result.update(normalized_valid=True,normalized_exact=selected==expected,format_changes=changes,
                      normalized_output=canonical)
    except ValueError as error:result['normalization_error']=str(error)
    # Classification does not turn a list containing the answer into a success.
    try:parsed=json.loads(single_json_fence(text))
    except ValueError:parsed=None
    if result['strict_exact']:category='strict_correct'
    elif result['normalized_exact']:category='format_only'
    elif isinstance(parsed,dict) and set(parsed)=={'candidate_ids'} and isinstance(parsed['candidate_ids'],list) and len(parsed['candidate_ids'])!=1:
        category='over_selection' if parsed['candidate_ids'] else 'empty_selection'
    elif result['normalized_valid']:category='wrong_candidate'
    elif parsed is None and result['censored']:category='incomplete_generation'
    else:category='invalid_protocol'
    result['category']=category
    return result


def audit(plan_path,output,*,timeout=60):
    plan_path=Path(plan_path).resolve();output=Path(output).resolve();started=time.monotonic()
    def check():
        if time.monotonic()-started>=timeout:raise TimeoutError('Lookup audit deadline')
    plan=json.loads(plan_path.read_text(encoding='utf-8'));inputs={str(plan_path):file_hash(plan_path)}
    for name,expected in plan['inputs'].items():
        check()
        if file_hash(name)!=expected:raise ValueError('Audit input changed: '+name)
        inputs[name]=expected
    def load(path):
        path=Path(path).resolve()
        if str(path) not in inputs:raise ValueError('Unbound audit input: '+str(path))
        return json.loads(path.read_text(encoding='utf-8'))
    output.mkdir(parents=True,exist_ok=False)
    result={'status':'running','scope':'Exposed known-name outputs; posthoc secondary format audit, not repair or model improvement',
        'primary_scores_unchanged':True,'production_promoted':False,'model_calls':0,'weight_updates':0,
        'training_allowed':False,'inputs':inputs,'reports':[]}
    def save():
        result['seconds']=round(time.monotonic()-started,3);atomic_json(output/'report.json',result)
    save()
    try:
        seen=set()
        with ProgressLog(output/'progress.jsonl',console=True) as progress:
            for entry in plan['reports']:
                check();path=Path(entry['report']).resolve();dataset=Path(entry['dataset']).resolve()
                if str(path) in seen:raise ValueError('Duplicate audit report')
                seen.add(str(path));data=load(path)
                if data['status']!='completed' or data['task_control']!='known_name_lookup':raise ValueError('Completed lookup report required')
                filename=data['cohort_file']
                if filename not in ('development.jsonl','evaluation.jsonl'):raise ValueError('Unexpected cohort file')
                source=dataset/filename;export=load(dataset/'export.json')
                if str(source) not in inputs or file_hash(source)!=data['dataset_sha256'] or export['dataset_sha256']!=data['dataset_sha256']:
                    raise ValueError('Lookup dataset drift')
                samples=[json.loads(line) for line in source.read_text(encoding='utf-8').splitlines()]
                expected_keys={(arm,i) for i,sample in enumerate(samples)
                    if 'locations' in json.loads(sample['completion'][0]['content']) for arm in ('base','adapter')}
                rows=[];keys=set()
                for row in data['rows']:
                    check();key=(row['arm'],row['sample'])
                    if key in keys or row['arm'] not in ('base','adapter'):raise ValueError('Duplicate/unknown model row')
                    keys.add(key)
                    mode=data.get('lookup_presentation','original')
                    actual,mapping,spec,_,meta=lookup_example(samples[row['sample']],presentation=mode)
                    mapping_hash=hashlib.sha256(json.dumps(mapping).encode()).hexdigest()
                    if mapping_hash!=row['candidate_mapping_sha256']:raise ValueError('Lookup catalog drift')
                    for name in ('query','expected_id','selection_rule'):
                        if row['lookup_control'][name]!=meta[name]:raise ValueError('Lookup truth/query drift')
                    prompt_hash=hashlib.sha256(json.dumps(actual['prompt'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                    if row.get('prompt_sha256',prompt_hash)!=prompt_hash:raise ValueError('Lookup prompt drift')
                    item=assess_output(row['output'],mapping,spec,meta['expected_id'],row['finish_reason'])
                    if item['strict_valid']!=row['candidate_id_valid'] or item['strict_exact']!=row['score']['teacher_selection_equal']:
                        raise ValueError('Original strict score mismatch')
                    rows.append(dict(item,arm=row['arm'],sample=row['sample'],query=meta['query'],expected_id=meta['expected_id']))
                if keys!=expected_keys:raise ValueError('Lookup report does not cover both complete symbol cohorts')
                summary={}
                for arm in ('base','adapter'):
                    selected=[r for r in rows if r['arm']==arm]
                    summary[arm]={'n':len(selected),'categories':dict(Counter(r['category'] for r in selected)),
                        **{k:sum(r[k] for r in selected) for k in ('strict_valid','strict_exact','normalized_valid','normalized_exact','censored')}}
                result['reports'].append({'source':str(path),'rows':rows,'summary':summary});save()
                try:progress.emit('lookup_audit',completed=len(result['reports']),total=len(plan['reports']))
                except OSError:result['telemetry_error']=True
        for name,expected in inputs.items():
            check()
            if file_hash(name)!=expected:raise ValueError('Audit input changed before publication')
        result['status']='completed'
    except Exception as error:
        result.update(status='incomplete',error_type=type(error).__name__);raise
    finally:save()
    return result
