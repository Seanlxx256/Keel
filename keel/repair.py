"""Bounded current-source evidence for a failed proposal verification."""
import ast
import json
import re

from .proposals import located_source_evidence


def repair_evidence(workspace, scope, verification):
    feedback, frames = [], {}
    for result in verification:
        try:
            records = json.loads(result.get('stdout', ''))['records']
        except (ValueError, KeyError, TypeError):
            records = []
        for record in records[:32]:
            if record.get('passed') is True:
                continue
            feedback.append({k: str(record.get(k, ''))[:500] for k in ('case', 'type', 'message')})
            eligible = [(name, int(line)) for name, line in re.findall(r'File "/workspace/([^"\n]+)", line (\d+)', str(record.get('traceback', '')))
                        if name in scope['files']]
            # Traceback order is outer caller to failure. Keep the failure and its direct caller,
            # not every enclosing client method along every repeated case.
            for name, line in eligible[-2:]:
                frames.setdefault(name, []).append(line)
        if not records:
            feedback.append({'returncode': result.get('returncode'),
                             'stdout': result.get('stdout', '')[:1000],
                             'stderr': result.get('stderr', '')[:1000]})
    evidence = []
    for name in scope['files']:
        if frames and name not in frames:
            continue
        text = workspace.read(name, role='implementer')['value']
        tree = ast.parse(text, filename=name)
        definitions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        positions = set()
        for line in (frames[name] if name in frames else scope.get('locations', {}).get(name, [])):
            containing = [n for n in definitions if n.lineno <= line <= n.end_lineno]
            if containing:
                positions.add(min(containing, key=lambda n: n.end_lineno - n.lineno).lineno)
        # Preserve a small definition window if no recorded position still resolves.
        if not positions and definitions:
            positions.add(definitions[0].lineno)
        payload = located_source_evidence(name, text, sorted(positions))
        payload['selection'] = 'innermost-two-scoped-traceback-frames' if frames else 'previous-locations'
        payload['omitted_declared_files'] = [n for n in scope['files'] if frames and n not in frames]
        workspace.ledger.add('file', 'implementer', 'Current source for verification repair', payload)
        evidence.append(payload)
    return evidence, feedback[:32]
