"""Prompt-only candidate token alignment; labels stay outside model inputs."""
import json
import math


SCORE_REPRESENTATIONS={'numbered_end':('numbered','candidate_end'),
    'numbered_after':('numbered','after_catalog'),
    'id_free_end':('without_ids','candidate_end'),'id_free_after':('without_ids','after_catalog'),
    'numbered_after_grouped':('numbered','after_catalog_grouped'),
    'id_free_after_grouped':('without_ids','after_catalog_grouped')}


def validate_score_representation(value,objective='candidate_scores'):
    if value!='legacy' and value not in SCORE_REPRESENTATIONS:
        raise ValueError('Unknown score representation')
    if objective!='candidate_scores' and value!='legacy':
        raise ValueError('Score representation requires candidate_scores objective')
    return value


def encode_score_input(tokenizer,messages,representation='legacy'):
    validate_score_representation(representation)
    if representation=='legacy':return encode_candidate_prompt(tokenizer,messages)
    mode,readout=SCORE_REPRESENTATIONS[representation]
    return encode_scoring_variant(tokenizer,messages,input_mode=mode,readout_mode=readout)


def encode_scoring_variant(tokenizer,messages,*,input_mode='numbered',readout_mode='candidate_end'):
    """Experimental 2x2 interface with a shared scoring instruction, no output schema.

    Fresh aligned training is required for each variant. The legacy encoder call
    remains byte compatible and is never silently routed through this interface.
    """
    import copy
    prompt=copy.deepcopy(messages)
    if not prompt or prompt[0]['role']!='system':raise ValueError('Require scoring system message')
    prompt[0]['content']=_scoring_instruction(input_mode)
    return encode_candidate_prompt(tokenizer,prompt,input_mode=input_mode,readout_mode=readout_mode)


def _scoring_instruction(input_mode):
    return ('Score each displayed source definition for relevance to the task. '
            'Symbols contain definition line and name'+
            (', followed by candidate ID.' if input_mode=='numbered' else '.')+
            ' Scores are read by the program; do not generate a selection.')


def json_value_spans(text):
    """Parse JSON structurally, retaining character offsets keyed by JSON path."""
    decoder=json.JSONDecoder();spans={}
    def white(i):
        while i<len(text) and text[i].isspace():i+=1
        return i
    def visit(i,path):
        i=white(i);start=i
        value,end=decoder.raw_decode(text,i)
        spans[path]=(start,end)
        if text[i]=='{':
            i=white(i+1);seen=set()
            while i<end-1:
                key,j=decoder.raw_decode(text,i)
                if not isinstance(key,str) or key in seen:raise ValueError('Ambiguous JSON object key')
                seen.add(key);j=white(j)
                if text[j]!=':':raise ValueError('Expected JSON colon')
                i=white(visit(j+1,path+(key,)))
                if i<end-1:
                    if text[i]!=',':raise ValueError('Expected JSON comma')
                    i=white(i+1)
        elif text[i]=='[':
            i=white(i+1);index=0
            while i<end-1:
                i=white(visit(i,path+(index,)));index+=1
                if i<end-1:
                    if text[i]!=',':raise ValueError('Expected JSON comma')
                    i=white(i+1)
        return end
    end=visit(0,())
    if white(end)!=len(text):raise ValueError('Trailing JSON data')
    return json.loads(text),spans


def encode_candidate_prompt(tokenizer,messages,*,input_mode='numbered',readout_mode='candidate_end'):
    """No assistant completion argument; scoring sees only the generation prefill."""
    if any(m['role']=='assistant' for m in messages):raise ValueError('Candidate scoring accepts prompt-only messages')
    if not messages or messages[-1]['role']!='user':raise ValueError('Require final user catalog')
    if input_mode not in ('numbered','without_ids') or readout_mode not in ('candidate_end','after_catalog','after_catalog_grouped'):
        raise ValueError('Unknown candidate representation policy')
    text=messages[-1]['content'];payload,spans=json_value_spans(text)
    identities=[(ri,si,row['path'],symbol[:]) for ri,row in enumerate(payload['structure']) for si,symbol in enumerate(row['symbols'])]
    if input_mode!='numbered' or readout_mode!='candidate_end':
        # This is a new scoring-only prompt interface, not compatible with an old
        # trained head by inference-only substitution. No completion is consumed.
        import copy
        payload=copy.deepcopy(payload)
        if 'scoring_readouts' in payload:raise ValueError('Reserved scoring field collision')
        if any(len(symbol)!=3 or type(symbol[2]) is not int for _,_,_,symbol in identities):
            raise ValueError('Require numbered source catalog')
        if input_mode=='without_ids':
            for row in payload['structure']:
                row['symbols']=[symbol[:2] for symbol in row['symbols']]
        if readout_mode=='after_catalog':
            payload['scoring_readouts']=[[path,*symbol] if input_mode=='numbered' else [path,*symbol[:2]]
                                         for _,_,path,symbol in identities]
        elif readout_mode=='after_catalog_grouped':
            # Preserve every path/line/name (and optional ID), but serialize the
            # shared file path once per file rather than once per definition.
            payload['scoring_readouts']=[{'path':row['path'],'symbols':copy.deepcopy(row['symbols'])}
                                         for row in payload['structure']]
        messages=[{'role':'system','content':_scoring_instruction(input_mode)},
                  *copy.deepcopy(messages[1:-1]),{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
        text=messages[-1]['content'];payload,spans=json_value_spans(text)
    marker='__KEEL_CANDIDATE_PAYLOAD_OFFSET__'
    if any(marker in m['content'] for m in messages):raise ValueError('Payload marker collision')
    render=lambda ms:tokenizer.apply_chat_template(ms,tokenize=False,add_generation_prompt=True,enable_thinking=False)
    prefix=render(messages)
    marked=render([*messages[:-1],{**messages[-1],'content':marker}])
    if marked.count(marker)!=1:raise ValueError('Chat template does not preserve one payload slot')
    before,after=marked.split(marker)
    if prefix!=before+text+after:raise ValueError('Chat template changed payload bytes')
    encoded=tokenizer(prefix,add_special_tokens=False,return_offsets_mapping=True)
    ids=encoded['input_ids'];offsets=encoded['offset_mapping']
    if len(ids)!=len(offsets) or tokenizer(prefix,add_special_tokens=False)['input_ids']!=ids:
        raise ValueError('Prompt token/offset identity changed')
    if ('goal',) not in spans:raise ValueError('Candidate scoring requires task goal')
    candidates=[];locations=set();candidate_ids=set()
    for index,(ri,si,path,symbol) in enumerate(identities):
            if len(symbol)!=3 or type(symbol[0]) is not int or type(symbol[2]) is not int:
                raise ValueError('Require exact numbered candidate tuple')
            location=f"{path}:{symbol[0]}";cid=symbol[2]
            if location in locations or cid in candidate_ids:raise ValueError('Duplicate candidate identity')
            locations.add(location);candidate_ids.add(cid)
            candidate_path=(('scoring_readouts',index) if readout_mode=='after_catalog' else
                            ('scoring_readouts',ri,'symbols',si) if readout_mode=='after_catalog_grouped' else
                            ('structure',ri,'symbols',si))
            start,end=spans[candidate_path]
            if readout_mode!='candidate_end' and start<spans[('structure',)][1]:
                raise ValueError('Readout precedes complete catalog')
            if spans[('goal',)][1]>start:raise ValueError('Task goal is not visible before candidate')
            start+=len(before);end+=len(before)
            positions=[i for i,(a,b) in enumerate(offsets) if start<=a<b<=end]
            if not positions:raise ValueError('Candidate lacks a fully contained token')
            position=positions[-1]
            candidates.append({'candidate_id':cid,'location':location,'token_position':position,
                               'character_span':[start,end],'json_path':list(candidate_path)})
    if not candidates or candidate_ids!=set(range(len(candidates))):raise ValueError('Incomplete numbered catalog')
    if len({c['token_position'] for c in candidates})!=len(candidates):raise ValueError('Shared candidate representation token')
    return {'input_ids':ids,'attention_mask':[1]*len(ids),'candidates':candidates,
            'scope':('Prompt-only causal candidate-end states; earlier candidates cannot see later catalog entries'
                     if readout_mode=='candidate_end' else
                     'Prompt-only readouts after complete catalog; readout order remains causal'),
            **({'representation_policy':{'input_mode':input_mode,'readout_mode':readout_mode}}
               if input_mode!='numbered' or readout_mode!='candidate_end' else {})}


def candidate_membership(features,teacher_ids):
    if (not isinstance(teacher_ids,list) or not teacher_ids or
        any(type(i) is not int for i in teacher_ids) or len(set(teacher_ids))!=len(teacher_ids)):
        raise ValueError('Require unique nonempty teacher IDs')
    allowed={c['candidate_id'] for c in features['candidates']}
    if not set(teacher_ids)<=allowed:raise ValueError('Unknown teacher candidate')
    return [int(c['candidate_id'] in teacher_ids) for c in features['candidates']]


def balanced_membership_loss(logits,labels):
    import torch
    target=torch.as_tensor(labels,dtype=logits.dtype,device=logits.device)
    if logits.ndim!=1 or target.shape!=logits.shape or not torch.all((target==0)|(target==1)):
        raise ValueError('One binary teacher-membership label per candidate required')
    positive=target==1;negative=target==0
    if not positive.any() or not negative.any():raise ValueError('Balanced pilot requires both membership classes')
    loss=torch.nn.functional.binary_cross_entropy_with_logits(logits,target,reduction='none')
    return (loss[positive].mean()+loss[negative].mean())/2


def select_candidates(candidates,probabilities,*,threshold=0.5,max_items=8):
    """Fixed score policy, never accept teacher labels or their cardinality."""
    if not 0<=threshold<=1 or type(max_items) is not int or max_items<1:raise ValueError('Invalid selection policy')
    if len(candidates)!=len(probabilities) or any(not math.isfinite(p) or not 0<=p<=1 for p in probabilities):
        raise ValueError('One finite probability per candidate required')
    ordered=sorted(zip(candidates,probabilities),key=lambda item:(-item[1],item[0]['location']))
    return [candidate for candidate,probability in ordered if probability>=threshold][:max_items]


def ranking_metrics(probabilities,labels):
    if len(probabilities)!=len(labels) or not labels or any(v not in (0,1) for v in labels):raise ValueError('Invalid membership ranking')
    total=sum(labels)
    if not total:raise ValueError('Require a positive teacher member')
    # Same-score groups use the precision at the whole group boundary.
    groups={}
    for probability,label in zip(probabilities,labels):
        if not math.isfinite(probability):raise ValueError('Nonfinite ranking probability')
        groups.setdefault(probability,[]).append(label)
    seen=hits=0;ap=0.
    for probability in sorted(groups,reverse=True):
        group=groups[probability];seen+=len(group);hits+=sum(group)
        ap+=sum(group)/total*hits/seen
    return {'teacher_average_precision':ap,'scope':'Teacher-set membership ranking; nonmembers are not certified irrelevant'}
