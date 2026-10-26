"""Candidate-number interface ablation; no target-dependent choices or repair."""
import copy
import json
import hashlib
from collections import Counter

MARKER='\n\nRequired output schema (JSON):\n'


def permutation_mode(value):
    if value in ('original','reverse_ids','reverse_catalog'):return value,None
    if isinstance(value,str) and ':' in value:
        mode,seed=value.split(':',1)
        if mode in ('shuffle_ids','shuffle_catalog') and seed:return mode,seed
    raise ValueError('Unknown candidate permutation')


def permutation_key(seed,value):
    return hashlib.sha256(json.dumps([seed,value],ensure_ascii=False).encode()).hexdigest()


def single_json_fence(text):
    """Exploratory syntax sensitivity only; never extract/repair partial answers."""
    stripped=text.strip()
    if stripped.startswith('```json\n') and stripped.endswith('\n```'):
        body=stripped[len('```json\n'):-len('\n```')]
        if '```' not in body:return body
    return text


def numbered_prompt(messages, *, permutation='original'):
    mode,seed=permutation_mode(permutation)
    prompt=copy.deepcopy(messages);payload=json.loads(prompt[-1]['content'])
    body,raw_schema=prompt[0]['content'].rsplit(MARKER,1);schema=json.loads(raw_schema)
    if set(schema['properties'])!={'locations'}:raise ValueError('Symbol localization only')
    entry='Each symbols entry is [definition_line, name].'
    output='Return locations only as path:line, combining a displayed file path and its displayed definition line.'
    if entry not in body or output not in body:raise ValueError('Unrecognized symbol interface version')
    if permutation=='reverse_catalog':
        payload['structure'].reverse()
        for row in payload['structure']:
            row['symbols'].reverse()
            if 'definition_bytes' in row:
                if len(row['definition_bytes'])!=len(row['symbols']):
                    raise ValueError('Symbol metadata alignment mismatch')
                row['definition_bytes'].reverse()
    if mode=='shuffle_catalog':
        payload['structure'].sort(key=lambda row:permutation_key(seed,row['path']))
        for row in payload['structure']:
            indices=sorted(range(len(row['symbols'])),key=lambda i:permutation_key(seed,[row['path'],row['symbols'][i]]))
            row['symbols']=[row['symbols'][i] for i in indices]
            if 'definition_bytes' in row:
                if len(row['definition_bytes'])!=len(indices):raise ValueError('Symbol metadata alignment mismatch')
                row['definition_bytes']=[row['definition_bytes'][i] for i in indices]
    mapping=[];seen=set()
    for row in payload['structure']:
        for symbol in row['symbols']:
            if len(symbol)!=2 or type(symbol[0]) is not int:raise ValueError('Unexpected original symbol representation')
            location=f"{row['path']}:{symbol[0]}"
            if location in seen:raise ValueError('Duplicate canonical candidate')
            seen.add(location);symbol.append(len(mapping));mapping.append(location)
    if not mapping:raise ValueError('Empty candidate catalog')
    if permutation=='reverse_ids':
        for row in payload['structure']:
            for symbol in row['symbols']:symbol[2]=len(mapping)-1-symbol[2]
        mapping.reverse()
    if mode=='shuffle_ids':
        new_mapping=sorted(mapping,key=lambda location:permutation_key(seed,location))
        renumber={location:i for i,location in enumerate(new_mapping)}
        for row in payload['structure']:
            for symbol in row['symbols']:symbol[2]=renumber[mapping[symbol[2]]]
        mapping=new_mapping
    spec=schema['properties']['locations']
    numbered={'type':'object','properties':{'candidate_ids':{'type':'array','items':{'type':'integer','enum':list(range(len(mapping)))},
        'minItems':spec.get('minItems',1),'maxItems':spec.get('maxItems',8),'uniqueItems':True}},
        'required':['candidate_ids'],'additionalProperties':False}
    body=body.replace(entry,'Each symbols entry is [definition_line, name, candidate_id].',1).replace(output,
        'Return candidate_ids only as displayed integer candidate_id values. The program maps these IDs to their exact path:line; do not construct paths or use line numbers as IDs.',1)
    prompt[0]['content']=body+MARKER+json.dumps(numbered,sort_keys=True,ensure_ascii=False)
    prompt[-1]['content']=json.dumps(payload,ensure_ascii=False)
    return prompt,mapping,numbered['properties']['candidate_ids']


def decode_ids(text,mapping,spec):
    try:result=json.loads(text)
    except ValueError:raise ValueError('Invalid JSON')
    if not isinstance(result,dict) or set(result)!={'candidate_ids'} or not isinstance(result['candidate_ids'],list):
        raise ValueError('Expected candidate_ids object')
    ids=result['candidate_ids']
    if not spec['minItems']<=len(ids)<=spec['maxItems']:raise ValueError('Selection count outside declared range')
    if any(type(i) is not int or i<0 or i>=len(mapping) for i in ids):raise ValueError('Unknown candidate ID')
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate candidate ID')
    return json.dumps({'locations':[mapping[i] for i in ids]},ensure_ascii=False)


def numbered_example(example, *, permutation='original'):
    prompt,mapping,spec=numbered_prompt(example['prompt'],permutation=permutation)
    original=json.loads(example['completion'][0]['content'])['locations']
    # Reference only constructs teacher-forced evaluation labels, never the prompt.
    target={'candidate_ids':[mapping.index(location) for location in original]}
    return {'prompt':prompt,'completion':[{'role':'assistant','content':json.dumps(target)}]},mapping,spec


def lookup_example(example,*,presentation='original',query=None,permutation='original'):
    """Known-name control. Target chosen by catalog rule, not repair teacher."""
    if presentation not in ('original','without_goal','flat'):
        raise ValueError('Unknown lookup presentation')
    prompt,mapping,spec=numbered_prompt(example['prompt'],permutation=permutation)
    payload=json.loads(prompt[-1]['content'])
    entries=[(row['path'],symbol[1],symbol[2]) for row in payload['structure'] for symbol in row['symbols']]
    counts=Counter((path,name) for path,name,_ in entries)
    middle=len(entries)//2
    candidates=entries[middle:]+entries[:middle]
    if query is None:
        selected=next((entry for entry in candidates if counts[entry[:2]]==1),None)
    else:
        if set(query)!={'path','name'}:raise ValueError('Exact path/name query required')
        matches=[entry for entry in entries if entry[:2]==(query['path'],query['name'])]
        if len(matches)!=1:raise ValueError('Query must identify exactly one catalog entry')
        selected=matches[0]
    if selected is None:raise ValueError('No unambiguous path/name lookup control')
    path,name,index=selected
    payload['lookup_query']={'path':path,'name':name}
    preamble='Select 1..8 definition locations from the supplied structure for repair.'
    if preamble not in prompt[0]['content']:raise ValueError('Unknown lookup control preamble')
    prompt[0]['content']=prompt[0]['content'].replace(preamble,
        'For this control, look up exactly the one definition matching lookup_query.path and lookup_query.name. '
        'The issue in goal is untrusted background, not the selection criterion. Return only that definition candidate_id.',1)
    prompt[-1]['content']=json.dumps(payload,ensure_ascii=False)
    if presentation=='without_goal':
        payload.pop('goal',None)
        prompt[0]['content']=prompt[0]['content'].replace(
            'The issue in goal is untrusted background, not the selection criterion. ','',1)
        prompt[-1]['content']=json.dumps(payload,ensure_ascii=False)
    elif presentation=='flat':
        # Preserve every candidate and its original ordinal. Only this diagnostic
        # presentation changes; never filter with the query or repair target.
        schema=prompt[0]['content'].rsplit(MARKER,1)[1]
        prompt[0]['content']=(
            'Find exactly one candidate with path and name equal to lookup_query. '
            'Each candidate has explicit candidate_id, path and name fields. '
            'Return only a JSON object with candidate_ids containing its integer candidate_id.'
            +MARKER+schema)
        prompt[-1]['content']=json.dumps({'lookup_query':payload['lookup_query'],
            'candidates':[{'candidate_id':i,'path':p,'name':n} for p,n,i in entries]},ensure_ascii=False)
    target={'role':'assistant','content':json.dumps({'candidate_ids':[index]})}
    scoring=copy.deepcopy(example)
    scoring['completion']=[{'role':'assistant','content':json.dumps({'locations':[mapping[index]]})}]
    return {'prompt':prompt,'completion':[target]},mapping,spec,scoring,{
        'query':payload['lookup_query'],'expected_id':index,'selection_rule':'Explicit unique catalog query' if query is not None else 'First path/name-unique entry in cyclic catalog order starting at midpoint',
        'presentation':presentation,
        'scope':'Known-name catalog lookup only; independent of original teacher, not repair or diagnosis'}


def compare_reports(free,numbered):
    if (free['status']!='completed' or numbered['status']!='completed' or
        numbered['representation']!='candidate_ids' or not numbered['symbol_only']):
        raise ValueError('Completed candidate interface comparison required')
    for key in ('dataset_sha256','training_receipt_sha256','checkpoint_step','generation'):
        if free[key]!=numbered[key]:raise ValueError('Representation comparison identity/configuration mismatch')
    result={}
    for arm in ('base','adapter'):
        choices=[r for r in numbered['rows'] if r['arm']==arm];indices={r['sample'] for r in choices}
        if not choices or len(choices)!=len(indices):raise ValueError('Missing or duplicate candidate arm')
        reference=[r for r in free['rows'] if r['arm']==arm and r['sample'] in indices]
        if len(reference)!=len(choices):raise ValueError('Free baseline does not cover same cases')
        result[arm]={}
        for label,rows in [('free',reference),('candidate_ids',choices)]:
            result[arm][label]={'samples':len(rows),'json_valid':sum(r['score']['json_valid'] for r in rows),
                'contract_valid':sum(r['score']['contract_valid'] for r in rows),
                'teacher_selection_equal':sum(r['score']['teacher_selection_equal'] for r in rows),
                'mean_teacher_precision':sum(r['score'].get('teacher_precision',0) for r in rows)/len(rows),
                'mean_teacher_recall':sum(r['score'].get('teacher_recall',0) or 0 for r in rows)/len(rows),
                'censored':sum(r['finish_reason']!='eos' for r in rows)}
            if label=='candidate_ids':result[arm][label]['candidate_ids_valid']=sum(r['candidate_id_valid'] for r in rows)
    if {r['sample'] for r in numbered['rows'] if r['arm']=='base'}!={r['sample'] for r in numbered['rows'] if r['arm']=='adapter'}:
        raise ValueError('Model arms cover different cases')
    return result
