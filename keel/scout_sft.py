"""Export reviewed development-only Scout demonstrations; no training runtime."""
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from compass.progress import atomic_json,ProgressLog
from .evaluation_protocol import implementation_hashes
from .scout_data_audit import _hash,_selection,_digest
from .scout_data_review import inspect_selection,load_event_pair


PROMPT_VERSION='scout-request-schema-v1'


def training_prompt(messages,schema):
    """Keep original messages, expose external schema to a future local model.

    This same function must be used by that model's inference adapter. Existing
    hosted Keel requests are not changed by this exporter.
    """
    prompt=copy.deepcopy(messages)
    if not prompt or any(not isinstance(m,dict) or not isinstance(m.get('content'),str) for m in prompt):
        raise ValueError('Unsupported prompt messages')
    suffix='\n\nRequired output schema (JSON):\n'+json.dumps(schema,sort_keys=True,ensure_ascii=False)
    if prompt[0].get('role')=='system':prompt[0]['content']+=suffix
    else:prompt.insert(0,{'role':'system','content':suffix.lstrip()})
    return prompt


def completion_labels(input_ids,completion_mask):
    """Mask prompt positions. IDs/mask must come from ONE full template encoding.

    This helper does not tokenize parts separately, shift causal-LM labels, or
    infer a target-tokenizer boundary from character counts.
    """
    if not input_ids or len(input_ids)!=len(completion_mask):raise ValueError('Token/mask length mismatch')
    if any(type(v) is not int or v<0 for v in input_ids):raise ValueError('Invalid token IDs')
    if any(type(v) not in (int,bool) or v not in (0,1) for v in completion_mask):raise ValueError('Mask must be binary')
    chosen=[i for i,v in enumerate(completion_mask) if v]
    if not chosen or chosen[0]==0 or chosen!=list(range(chosen[0],chosen[-1]+1)):
        raise ValueError('Require prompt and one nonempty contiguous completion span')
    return [token if active else -100 for token,active in zip(input_ids,completion_mask)]


def character_mask_fixture(sample_id,prompt,content):
    """Masking algebra only: never model tokens, template boundaries or SFT input."""
    prefix=json.dumps(prompt,ensure_ascii=False)+'\nASSISTANT_COMPLETION:\n'
    ids=[ord(c) for c in prefix+content];mask=[0]*len(prefix)+[1]*len(content)
    labels=completion_labels(ids,mask)
    assert all(v==-100 for v in labels[:len(prefix)])
    assert labels[len(prefix):]==ids[len(prefix):]
    return {'sample_id':sample_id,'prompt_character_positions_masked':len(prefix),
            'completion_character_positions_labelled':len(content),'passed':True}


def _base_source(evidence,remaining):
    repo=Path(evidence['repo']);spec=evidence['base_commit']+':'+evidence['path']
    command=['git','-c','safe.directory='+repo.as_posix(),'-C',str(repo)]
    size=subprocess.run([*command,'cat-file','-s',spec],capture_output=True,check=True,timeout=min(10,remaining()))
    if not 0<int(size.stdout)<=1048576:raise ValueError('Source evidence size outside bound')
    raw=subprocess.run([*command,'show',spec],capture_output=True,check=True,timeout=min(10,remaining())).stdout
    if len(raw)!=int(size.stdout) or hashlib.sha256(raw).hexdigest()!=evidence['source_sha256']:
        raise ValueError('Reviewed base source changed')
    return evidence['source_sha256']


def export_development(review_dir,output,*,timeout=120,source_reader=None):
    if type(timeout) is not int or not 1<=timeout<=1800:raise ValueError('Export deadline1..1800seconds')
    review_dir,output=map(lambda p:Path(p).resolve(),(review_dir,output))
    output.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    def remaining():
        seconds=timeout-(time.monotonic()-started)
        if seconds<=0:raise TimeoutError('Scout export deadline exceeded')
        return seconds
    def check():remaining()
    result={'schema_version':1,'status':'running','model_calls':0,'weight_updates':0,'inputs':{},'samples':[],
        'implementation':implementation_hashes(Path(__file__).resolve().parents[1]),
        'allowed_use':'development_smoke_only','independent_evaluation_eligible':False,
        'prompt_version':PROMPT_VERSION,'target_tokenizer_validation':'pending_model_selection',
        'scope':'Explicit reviewed raw prompt/completion export. No dataset split, model download, GPU job or generalization result.'}
    def save():
        result['seconds']=round(time.monotonic()-started,3);atomic_json(output/'export.json',result)
    save();source_reader=source_reader or _base_source
    def load(path):
        expected=_hash(path,check);value=json.loads(path.read_text(encoding='utf-8'))
        result['inputs'][str(path)]=expected;return value,expected
    try:
        approval,approval_hash=load(review_dir/'developer-assessments.json')
        reviewed,review_hash=load(review_dir/'review.json')
        evidence,evidence_hash=load(review_dir/'developer-source-evidence.json')
        if (reviewed['status']!='completed' or approval['source_review_sha256']!=review_hash
                or approval['source_evidence_sha256']!=evidence_hash):raise ValueError('Review identity mismatch')
        for name,expected in reviewed['inputs'].items():
            if _hash(Path(name),check)!=expected:raise ValueError('Review source changed')
            result['inputs'][name]=expected
        by_id={item['sample_id']:item for item in reviewed['items']}
        approved=[a for a in approval['items'] if a['decision']=='approved_development_smoke']
        if not approved:raise ValueError('No explicit development approvals')
        dataset=[];fixtures=[];seen=set()
        with ProgressLog(output/'progress.jsonl',console=True) as progress:
            for a in approved:
                check()
                try:progress.emit('export',completed=len(dataset),total=len(approved))
                except OSError:result['telemetry_error']=True
                if (a['training_use']!='development_smoke_only' or a['independent_evaluation_eligible'] is not False
                        or a['raw_target_modified'] is not False or not a.get('reviewer')
                        or not a.get('rationale') or a.get('input_goal_matches_original_receipt') is not True):
                    raise ValueError('Approval exceeds reviewed development scope')
                row=by_id[a['sample_id']]
                if (row['decision']!='needs_semantic_review' or row['violations']
                        or row['example_sha256']!=a['example_sha256'] or row['instance_id']!=a['instance_id']):
                    raise ValueError('Approval contradicts contract review')
                if a['sample_id'] in seen:raise ValueError('Duplicate approved sample')
                seen.add(a['sample_id'])
                request,response=load_event_pair(row['transcript'],row['request_line'],row['response_line'],2097152,check)
                screened=_selection(request,response)
                if not screened or screened.get('example_sha256')!=a['example_sha256']:
                    raise ValueError('Original example changed')
                fresh=inspect_selection(request,response,{})
                if fresh['decision']!='needs_semantic_review':raise ValueError('Current contract check failed')
                messages=request['args'][0] if request.get('args') else request['kwargs']['messages']
                payload=json.loads(messages[-1]['content'])
                receipt,receipt_hash=load(Path(a['input_receipt']['path']))
                if receipt_hash!=a['input_receipt']['sha256'] or payload['goal']!=receipt['goal']:
                    raise ValueError('Original goal receipt changed')
                if not a.get('source_evidence'):raise ValueError('Missing semantic source evidence')
                for source in a['source_evidence']:
                    if source not in evidence['items'] or source['receipt_sha256']!=receipt_hash:
                        raise ValueError('Source evidence not reviewed')
                    if source_reader(source,remaining)!=source['source_sha256']:raise ValueError('Base source mismatch')
                prompt=training_prompt(messages,request['kwargs']['schema'])
                completion=[{'role':'assistant','content':response['content']}]
                dataset.append({'prompt':prompt,'completion':completion})
                result['samples'].append({'sample_id':a['sample_id'],'instance_id':a['instance_id'],
                    'kind':row['kind'],'example_sha256':a['example_sha256'],'approval_sha256':approval_hash,
                    'prompt_sha256':_digest(prompt),'completion_sha256':_digest(completion),
                    'target_unchanged':True,'use':'development_smoke_only'})
                # Deterministic character fixture exercises masking algebra only.
                # These are NOT model tokens, chat-template boundaries or training inputs.
                fixtures.append(character_mask_fixture(a['sample_id'],prompt,response['content']))
        destination=output/'development.jsonl'
        with destination.open('x',encoding='utf-8',newline='\n') as stream:
            for example in dataset:stream.write(json.dumps(example,ensure_ascii=False)+'\n')
            stream.flush();os.fsync(stream.fileno())
        atomic_json(output/'mask-fixture.json',{'status':'passed','kind':'character_fixture_only',
            'real_model_tokenizer_verified':False,'items':fixtures})
        for name,expected in result['inputs'].items():
            if _hash(Path(name),check)!=expected:raise ValueError('Export input changed before publication')
        result.update(status='exported_development_only',sample_count=len(dataset),
            tasks=dict(Counter(item['instance_id'] for item in result['samples'])),
            dataset_sha256=_hash(destination,check),
            mask_fixture_sha256=_hash(output/'mask-fixture.json',check))
    except (ValueError,KeyError,OSError,subprocess.SubprocessError,TimeoutError) as error:
        result.update(status='incomplete',error_type=type(error).__name__)
    finally:save()
    return result
