"""Append explicitly approved captured-source controls, never repair teacher labels."""
from collections import Counter
import json
import os
from pathlib import Path
import time

from compass.progress import atomic_json,ProgressLog
from .evaluation_protocol import implementation_hashes
from .scout_data_audit import _digest,_hash,_linked,_selection
from .scout_data_review import inspect_selection,load_event_pair
from .scout_source_evidence import inspect_source
from .scout_sft import training_prompt,character_mask_fixture,PROMPT_VERSION


def export_bound(base_dataset,collection,review_path,reservation_path,output,*,timeout=60):
    base_dataset,collection,review_path,reservation_path,output=[Path(p).resolve() for p in
        (base_dataset,collection,review_path,reservation_path,output)]
    started=time.monotonic()
    def check():
        if time.monotonic()-started>=timeout:raise TimeoutError('Captured-source export deadline')
    output.mkdir(parents=True,exist_ok=False)
    result={'status':'running','inputs':{},'samples':[],'model_calls':0,'weight_updates':0,
        'implementation':implementation_hashes(Path(__file__).resolve().parents[1]),
        'allowed_use':'development_smoke_only','independent_evaluation_eligible':False,
        'prompt_version':PROMPT_VERSION,'target_tokenizer_validation':'pending_model_selection',
        'scope':'Append reviewed exposed controls from exact captured source; not new training or independent evaluation'}
    def save():
        result['seconds']=round(time.monotonic()-started,3);atomic_json(output/'export.json',result)
    def bind(path,expected=None):
        path=Path(path).resolve()
        if _linked(path):raise ValueError('Linked export evidence')
        actual=_hash(path,check)
        if expected is not None and actual!=expected:raise ValueError('Export evidence changed: '+str(path))
        if str(path) in result['inputs'] and result['inputs'][str(path)]!=actual:raise ValueError('Evidence changed during export')
        result['inputs'][str(path)]=actual;return actual
    def load(path):
        bind(path);return json.loads(Path(path).read_text(encoding='utf-8'))
    save()
    try:
        old=load(base_dataset/'export.json');approval=load(review_path);run=load(collection/'collection.json');reservation=load(reservation_path)
        if old['status']!='exported_development_only' or old['prompt_version']!=PROMPT_VERSION:
            raise ValueError('Reviewed compatible development base required')
        if approval['status']!='reviewed_pending_export' or run['status']!='collected_pending_review':
            raise ValueError('Completed collection and explicit developer review required')
        for evidence_inputs in (old['inputs'],approval['inputs']):
            for name,expected in evidence_inputs.items():bind(name,expected)
        if approval['inputs'].get(str(collection/'collection.json'))!=result['inputs'][str(collection/'collection.json')]:
            raise ValueError('Review belongs to different collection')
        bind(base_dataset/'development.jsonl',old['dataset_sha256'])
        old_bytes=(base_dataset/'development.jsonl').read_bytes()
        if not old_bytes.endswith(b'\n'):raise ValueError('Base dataset framing changed')
        examples=[json.loads(line) for line in old_bytes.decode('utf-8').splitlines()]
        if len(examples)!=old['sample_count'] or len(old['samples'])!=len(examples):raise ValueError('Base dataset count mismatch')
        result['samples']=list(old['samples']);seen={s['sample_id'] for s in old['samples']};states={s['example_sha256'] for s in old['samples']}
        if len(seen)!=len(examples) or len(states)!=len(examples):raise ValueError('Duplicate base examples')
        for example,sample in zip(examples,old['samples']):
            if _digest(example['prompt'])!=sample['prompt_sha256'] or _digest(example['completion'])!=sample['completion_sha256']:
                raise ValueError('Base sample identity mismatch')
        blocked={key.rsplit('-',1)[0] for key,value in reservation['assignments']['tasks'].items()
                 if value['partition'] in ('transfer_review','quarantine')}
        by_task={row['instance_id']:row for row in run['tasks']}
        for row in run['tasks']:
            for name,identity in row['evidence'].items():
                if not Path(name).resolve().is_relative_to(collection):raise ValueError('Evidence outside original collection')
                bind(name,identity)
        added=[];approved=[a for a in approval['items'] if a['decision']=='approved_development_smoke']
        if not approved:raise ValueError('No explicit captured-source approvals')
        with ProgressLog(output/'progress.jsonl',console=True) as progress:
            for a in approved:
                check()
                if (not a.get('reviewer') or not a.get('rationale') or a['training_use']!='development_smoke_only'
                    or a['independent_evaluation_eligible'] is not False or a['raw_target_modified'] is not False
                    or a['original_goal_matches'] is not True):raise ValueError('Approval scope is not development-only')
                if a['instance_id'].rsplit('-',1)[0] in blocked:raise ValueError('Approved task crosses reserved repository boundary')
                task=by_task[a['instance_id']]
                if task['status']!='collected' or a['sample_id'] in seen:raise ValueError('Repeated or incomplete collection task')
                transcript=Path(a['transcript']).resolve();bind(transcript,a['transcript_sha256'])
                if not transcript.is_relative_to(collection/a['instance_id']):raise ValueError('Transcript belongs to another task')
                request,response=load_event_pair(transcript,a['request_line'],a['response_line'],2097152,check)
                if a['sample_id']!=_digest([a['transcript_sha256'],a['request_line'],a['response_line']]):raise ValueError('Approval event identity mismatch')
                link=a['source_binding'];source=Path(link['path']).resolve()
                if not source.is_relative_to(collection/a['instance_id']):raise ValueError('Source binding outside task')
                if request.get('source_binding')!=link or response.get('source_binding')!=link:raise ValueError('Request/response source binding mismatch')
                bind(source,link['sha256']);binding=load(source)
                completion=load(source.parent/'result.json')
                if completion['source_stable'] is not True or completion['source_binding']!=link:raise ValueError('Source changed during collection')
                if binding['task']['instance_id']!=a['instance_id']:raise ValueError('Captured task mismatch')
                payload=json.loads(request['args'][0][-1]['content'])
                if 'catalog_page' in payload or payload['goal']!=binding['task']['problem_statement']:
                    raise ValueError('Paged or augmented input is not an original final localization label')
                screened=_selection(request,response);contract=inspect_selection(request,response,{})
                if not screened or screened['issues'] or contract['decision']!='needs_semantic_review':raise ValueError('Current selection contract failed')
                if screened['example_sha256'] in states:raise ValueError('Duplicate logical example')
                target=json.loads(response['content']);field=screened['kind']
                selected={value.rpartition(':')[0] if field=='locations' else value for value in target[field]}
                sources={}
                for name in selected:
                    evidence=binding['catalog_sources'][name];obj=Path(evidence['object']).resolve()
                    if not obj.is_relative_to(collection/a['instance_id']):raise ValueError('Source object outside captured task')
                    bind(obj,evidence['sha256']);sources[name]=obj.read_bytes()
                facts=inspect_source(request,response,{'goal':binding['task']['problem_statement']},sources)
                if not facts['goal_matches_original_receipt'] or any(not f['source_available'] or
                    (field=='locations' and not f['exact_base_symbol']) for f in facts['selected_source_facts']):raise ValueError('Captured declaration/source mismatch')
                prompt=training_prompt(request['args'][0],request['kwargs']['schema'])
                example={'prompt':prompt,'completion':[{'role':'assistant','content':response['content']}]}
                added.append(example);examples.append(example);seen.add(a['sample_id']);states.add(screened['example_sha256'])
                result['samples'].append({'sample_id':a['sample_id'],'instance_id':a['instance_id'],'kind':field,
                    'example_sha256':screened['example_sha256'],'approval_sha256':result['inputs'][str(review_path)],
                    'prompt_sha256':_digest(prompt),'completion_sha256':_digest(example['completion']),
                    'target_unchanged':True,'use':'development_smoke_only','source_backend':'captured_catalog_cas',
                    'source_binding':link,'source_facts':facts})
                try:progress.emit('bound_export',completed=len(added),total=len(approved))
                except OSError:result['telemetry_error']=True
        with (output/'development.jsonl').open('xb') as stream:
            stream.write(old_bytes)
            for example in added:stream.write((json.dumps(example,ensure_ascii=False)+'\n').encode('utf-8'))
            stream.flush();os.fsync(stream.fileno())
        fixtures=[character_mask_fixture(sample['sample_id'],example['prompt'],example['completion'][0]['content'])
                  for sample,example in zip(result['samples'],examples)]
        atomic_json(output/'mask-fixture.json',{'status':'passed','kind':'character_fixture_only',
            'real_model_tokenizer_verified':False,'items':fixtures})
        for name,identity in result['inputs'].items():
            if _hash(Path(name),check)!=identity:raise ValueError('Export evidence changed before publication')
        result.update(status='exported_development_only',sample_count=len(examples),
            tasks=dict(Counter(s['instance_id'] for s in result['samples'])),
            dataset_sha256=_hash(output/'development.jsonl',check),mask_fixture_sha256=_hash(output/'mask-fixture.json',check),
            migration={'base_dataset':str(base_dataset),'base_samples_unchanged':len(old['samples']),
                'added_captured_source_samples':len(added),'source_review':str(review_path)},
            not_exported=[{'sample_id':a['sample_id'],'decision':a['decision']} for a in approval['items'] if a not in approved])
    except Exception as error:
        result.update(status='incomplete',error_type=type(error).__name__);raise
    finally:save()
    return result
