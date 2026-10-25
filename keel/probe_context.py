"""Static call-context hints from current source, never invented fixture values."""
import ast
import hashlib


def context_inventory(path, text, symbols):
    definitions={node.name:node for node in ast.parse(text).body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
    if not isinstance(symbols,list) or not symbols or len(symbols)>8 or any(name not in definitions for name in symbols):
        raise ValueError('Select 1..8 exact top-level source functions')
    rows=[]
    for name in symbols:
        node=definitions[name]
        parameters={arg.arg for arg in [*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs]}
        accesses=set();callees=set()
        for child in ast.walk(node):
            if isinstance(child,ast.Attribute):
                parts=[];root=child
                while isinstance(root,ast.Attribute):
                    parts.append(root.attr);root=root.value
                if isinstance(root,ast.Name) and root.id in parameters:
                    accesses.add('.'.join([root.id,*reversed(parts)]))
            if isinstance(child,ast.Call) and isinstance(child.func,ast.Name) and child.func.id in definitions:
                callees.add(child.func.id)
        if len(accesses)>32:
            raise ValueError('Selected call context exceeds bounded inventory')
        rows.append({'function':name,'line':node.lineno,'parameters':sorted(parameters),
                     'parameter_attribute_accesses':sorted(accesses),'local_callees':sorted(callees)})
    return {'path':path,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),'functions':rows,
            'scope':'Syntactic access inventory, including conditional/nested accesses; not proof every attribute is required on every path. '
                    'Use real constructors/test fixtures where possible. Default None does not prove a call with None is valid. '
                    'No context values or source fixes are invented.'}
