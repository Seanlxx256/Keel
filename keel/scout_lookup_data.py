"""Mechanical diverse lookup data from training catalogs, without repair targets."""
import hashlib
import json
from .scout_candidate_ids import lookup_example


def lookup_variants(example):
    control,mapping,spec,scoring,meta=lookup_example(example,presentation='without_goal')
    payload=json.loads(control['prompt'][-1]['content'])
    entries=[(row['path'],symbol[1]) for row in payload['structure'] for symbol in row['symbols']]
    from collections import Counter
    counts=Counter(entries)
    held=(meta['query']['path'],meta['query']['name'])
    eligible=[entry for entry in entries if counts[entry]==1 and entry!=held]
    ordered=sorted(eligible,key=lambda entry:hashlib.sha256(json.dumps(entry).encode()).hexdigest())
    if len(ordered)<2:raise ValueError('Need two unique queries beyond frozen control')
    rows=[];manifest=[]
    for path,name in ordered[:2]:
        query={'path':path,'name':name}
        for mode in ('original','reverse_ids','reverse_catalog'):
            actual,_,_,_,info=lookup_example(example,presentation='without_goal',query=query,permutation=mode)
            rows.append(actual);manifest.append({'query':query,'permutation':mode,'expected_id':info['expected_id']})
    return rows,{'excluded_query':meta['query'],'variants':manifest,
                 'rule':'Two SHA256-sorted unique path/name queries excluding frozen midpoint control; three fixed permutations'}
