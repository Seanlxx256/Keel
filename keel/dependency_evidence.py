"""Bounded static API discovery in the operator's fixed verifier image."""
import json
import re
import ast

from .core import PolicyDenied


def referenced_calls(text, module):
    """Direct import aliases only; do not guess receiver types or replacement APIs."""
    if not isinstance(module, str) or not all(p.isidentifier() for p in module.split('.')):
        raise ValueError('Python module name required')
    tree = ast.parse(text)
    modules, names, found = set(), {}, set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module:
                    modules.add(alias.asname or module)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module:
            for alias in node.names:
                names[alias.asname or alias.name] = alias.name
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name) and function.value.id in modules:
            found.add(function.attr)
        elif isinstance(function, ast.Name) and function.id in names:
            found.add(names[function.id])
    return sorted(found)


def validate_modules(modules):
    if not isinstance(modules, list) or len(modules) > 3:
        raise ValueError('At most three localization dependency modules allowed')
    requests = []
    for row in modules:
        if not isinstance(row, dict) or set(row) != {'module', 'distribution', 'version'}:
            raise ValueError('Dependency module requires module/distribution/version')
        if not isinstance(row['module'], str) or not all(p.isidentifier() for p in row['module'].split('.')):
            raise ValueError('Python module name required')
        requests.append({k: row[k] for k in ('distribution', 'version')} | {'symbols': ['validation']})
    validate_requests(requests)


def compact_contracts(evidence):
    """Public and protocol signatures; preserve full scan separately in the ledger."""
    result = []
    for payload in evidence:
        signatures, omitted = [], 0
        for record in payload['records']:
            name = record['symbol'].split('.')[-1]
            if name.startswith('_') and not (name.startswith('__') and name.endswith('__')):
                omitted += 1
                continue
            if record.get('signature_truncated'):
                raise ValueError('Cannot supply a truncated dependency signature as a complete contract')
            signatures.append(record['signature'])
        result.append({'distribution': payload['distribution'], 'version': payload['version'],
            'signatures': signatures, 'private_records_omitted': omitted,
            'inventory_sha256': payload['inventory_sha256'],
            'scope': payload['scope']})
    return result


def collect_for_localization(workspace, scope, modules):
    validate_modules(modules)
    requests = []
    for module in modules:
        symbols = set()
        for name in scope['files']:
            text = workspace.read(name, role='scout')['value']
            symbols.update(referenced_calls(text, module['module']))
        if not symbols:
            raise ValueError('Selected source has no directly referenced calls for dependency module')
        requests.append({k: module[k] for k in ('distribution', 'version')} |
            {'symbols': sorted(symbols), 'include_methods': True})
    return compact_contracts(collect(workspace, requests)) if requests else []


SCAN = r'''
import ast, hashlib, importlib.metadata, json, pathlib, sys
request = json.loads(sys.argv[1])
dist = importlib.metadata.distribution(request['distribution'])
if dist.version != request['version']:
    raise ValueError('Installed dependency version differs from requested target')
if dist.files is None:
    raise ValueError('Distribution has no file inventory')
root = pathlib.Path(dist.locate_file('')).resolve()
records, fingerprints, total = [], [], 0
for item in sorted(dist.files, key=str):
    relative = pathlib.PurePosixPath(str(item).replace('\\', '/'))
    if relative.suffix != '.py' or '..' in relative.parts:
        continue
    parts = list(relative.with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    if not parts or not all(part.isidentifier() for part in parts):
        continue
    path = pathlib.Path(dist.locate_file(item)).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Distribution source escapes installation root')
    if path.stat().st_size > 2_000_000:
        raise ValueError('Dependency source file exceeds byte cap')
    raw = path.read_bytes()
    total += len(raw)
    if len(fingerprints) >= 200 or total > 5_000_000:
        raise ValueError('Dependency scan exceeds file/byte cap')
    file_hash = hashlib.sha256(raw).hexdigest()
    fingerprints.append([str(relative), file_hash])
    tree = ast.parse(raw, filename=str(relative))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in request['symbols']:
            signature = ('class ' + node.name if isinstance(node, ast.ClassDef) else
                ('async def ' if isinstance(node, ast.AsyncFunctionDef) else 'def ') + node.name + '(' + ast.unparse(node.args) + ')')
            records.append({'symbol': node.name, 'module': '.'.join(parts), 'file': str(relative),
                'line': node.lineno, 'signature': signature[:500], 'signature_truncated': len(signature) > 500,
                'doc_summary': (ast.get_docstring(node) or '').split('\n')[0][:240], 'source_sha256': file_hash})
            if isinstance(node, ast.ClassDef) and request.get('include_methods', False):
                for member in node.body:
                    if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    signature = (('async def ' if isinstance(member, ast.AsyncFunctionDef) else 'def ')
                        + node.name + '.' + member.name + '(' + ast.unparse(member.args) + ')')
                    records.append({'symbol': node.name+'.'+member.name, 'module': '.'.join(parts),
                        'file': str(relative), 'line': member.lineno, 'signature': signature[:500],
                        'signature_truncated': len(signature) > 500,
                        'doc_summary': (ast.get_docstring(member) or '').split('\n')[0][:240],
                        'source_sha256': file_hash})
            if len(records) > (60 if request.get('include_methods', False) else 20):
                raise ValueError('Too many symbol matches; narrow requested symbols')
print(json.dumps({'distribution': request['distribution'], 'version': dist.version,
    'records': records, 'files_scanned': len(fingerprints), 'bytes_scanned': total,
    'inventory_sha256': hashlib.sha256(json.dumps(fingerprints).encode()).hexdigest(),
    'complete': True, 'scope': 'Static top-level definitions and optionally direct class methods; inheritance, imports/reexports and dynamic APIs are not resolved.'}))
'''


def validate_requests(requests):
    if not isinstance(requests, list) or len(requests) > 3:
        raise ValueError('At most three dependency evidence requests are allowed')
    names = set()
    for request in requests:
        if (not isinstance(request, dict) or not {'distribution', 'version', 'symbols'} <= request.keys()
                or request.keys() - {'distribution', 'version', 'symbols', 'include_methods'}):
            raise ValueError('Dependency request requires distribution/version/symbols and optional include_methods')
        if 'include_methods' in request and type(request['include_methods']) is not bool:
            raise ValueError('include_methods must be boolean')
        name = request['distribution']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', name):
            raise ValueError('Invalid dependency distribution name')
        canonical = re.sub(r'[-_.]+', '-', name).lower()
        if canonical in names:
            raise ValueError('Duplicate dependency evidence request')
        names.add(canonical)
        if not isinstance(request['version'], str) or not 1 <= len(request['version']) <= 64:
            raise ValueError('Dependency evidence requires an exact version')
        symbols = request['symbols']
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= 8 or any(
                not isinstance(symbol, str) or not symbol.isidentifier() or len(symbol) > 100 for symbol in symbols):
            raise ValueError('Dependency symbols require 1..8 Python identifiers')


def collect(workspace, requests):
    validate_requests(requests)
    if requests and workspace.runner.backend != 'docker':
        raise PolicyDenied('Dependency evidence requires the configured Docker image; no host fallback')
    directory = workspace.trace.path.parent/'dependency-evidence'
    evidence = []
    for index, request in enumerate(requests):
        workspace.budget.charge_tool()
        workspace.trace.emit('scout', 'dependency_scan_started', distribution=request['distribution'])
        result = workspace.runner.run(['python', '-I', '-c', SCAN, json.dumps(request)],
                                      workspace.root, min(30, workspace.budget.remaining))
        directory.mkdir(exist_ok=True)
        (directory/f'{index}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        if result['returncode'] != 0 or result['timeout']:
            raise ValueError('Dependency evidence scan failed; inspect saved execution logs')
        if len(result['stdout'].encode()) > 100_000:
            raise ValueError('Dependency evidence response exceeds byte cap')
        payload = json.loads(result['stdout'])
        if (payload.get('complete') is not True or payload.get('distribution') != request['distribution']
                or payload.get('version') != request['version']):
            raise ValueError('Dependency evidence identity or completeness mismatch')
        fact = workspace.ledger.add('symbol', 'scout', 'Installed dependency API evidence', payload)
        workspace.trace.emit('scout', 'dependency_scan_finished', fact_id=fact,
                             distribution=request['distribution'], matches=len(payload['records']))
        evidence.append(payload)
    return evidence
