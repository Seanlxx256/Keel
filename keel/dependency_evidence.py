"""Bounded static API discovery in the operator's fixed verifier image."""
import json
import re

from .core import PolicyDenied


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
            if len(records) > 20:
                raise ValueError('Too many symbol matches; narrow requested symbols')
print(json.dumps({'distribution': request['distribution'], 'version': dist.version,
    'records': records, 'files_scanned': len(fingerprints), 'bytes_scanned': total,
    'inventory_sha256': hashlib.sha256(json.dumps(fingerprints).encode()).hexdigest(),
    'complete': True, 'scope': 'Static top-level definitions only; imports/reexports and dynamic APIs are not resolved.'}))
'''


def validate_requests(requests):
    if not isinstance(requests, list) or len(requests) > 3:
        raise ValueError('At most three dependency evidence requests are allowed')
    names = set()
    for request in requests:
        if not isinstance(request, dict) or set(request) != {'distribution', 'version', 'symbols'}:
            raise ValueError('Dependency request requires distribution/version/symbols')
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
