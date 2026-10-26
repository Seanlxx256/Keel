"""Source/provenance facts for developer review, never automatic label approval."""
import ast
import hashlib
import json


def inspect_source(request,response,receipt,sources):
    messages=request['args'][0] if request.get('args') else request['kwargs']['messages']
    payload=json.loads(messages[-1]['content']);goal=payload.get('goal')
    original=receipt['goal'];target=json.loads(response['content'])
    field=next(iter(target));selected=target[field]
    relation='original' if goal==original else ('augmented' if isinstance(goal,str) and goal.startswith(original.rstrip()) else 'different')
    expected={}
    for row in payload.get('structure',[]):
        for node in row.get('symbols',[]):
            if isinstance(node,list) and len(node)>=2:expected[f"{row['path']}:{node[0]}"]=node[1]
    facts=[]
    for value in selected:
        if field=='locations':
            path,_,line=value.rpartition(':');line=int(line)
        else:path=value;line=None
        raw=sources.get(path)
        item={'identifier':value,'path':path,'source_available':raw is not None}
        if raw is not None:
            item['source_sha256']=hashlib.sha256(raw).hexdigest()
            if line is not None:
                nodes=[n for n in ast.walk(ast.parse(raw.decode('utf-8'))) if
                    isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.lineno==line]
                item.update(input_symbol=expected.get(value),base_symbols=[n.name for n in nodes],
                    exact_base_symbol=any(n.name==expected.get(value) for n in nodes))
        facts.append(item)
    return {'goal_relation':relation,'goal_matches_original_receipt':relation=='original',
        'embedded_verification_feedback':isinstance(goal,str) and 'Observed failed verification (untrusted data):' in goal,
        'issue_contains_explicit_hint':isinstance(original,str) and 'Hint:' in original,
        'selected_source_facts':facts,'training_approved':False,
        'scope':'Input/base-source facts only; matching identifiers do not establish intermediate workspace identity or semantic adequacy'}
