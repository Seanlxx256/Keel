"""Bounded current-source evidence for a failed proposal verification."""
import ast
import json
import re

from .proposals import located_source_evidence


def select_repair_evidence(model, workspace, goal, scope, feedback, settings):
    """Acquire explicitly selected current definitions within the original write scope."""
    from .localization import select, symbol_structure, ANCHOR_INSTRUCTION
    from .core import ModelError, PolicyDenied
    source = {name: workspace.read(name, role='implementer')['value'] for name in scope['files']}
    structure = [symbol_structure(name, text) for name, text in source.items()]
    chosen = select(model, workspace, goal, settings, stage='repair-evidence-selection',
        data={'structure': structure, 'verification_errors': feedback,
              'proposal_input_limit_bytes': settings.get('max_context_bytes', 12000)},
        keys=('locations',), instruction=ANCHOR_INSTRUCTION)
    allowed = {f"{row['path']}:{line}": (row['path'], line) for row in structure for line, _ in row['symbols']}
    if not set(chosen['locations']) <= allowed.keys():
        raise ModelError('Repair evidence locations must belong to original declared files and displayed catalog')
    locations = {}
    for identifier in chosen['locations']:
        name, line = allowed[identifier]
        locations.setdefault(name, []).append(line)
    evidence = []
    for name, positions in locations.items():
        current = workspace.read(name, role='implementer')['value']
        if current != source[name]:
            raise PolicyDenied('Source changed during repair evidence selection')
        payload = located_source_evidence(name, current, positions)
        payload['selection'] = 'model-selected-current-declared-definitions'
        payload['omitted_declared_files'] = [n for n in scope['files'] if n not in locations]
        workspace.ledger.add('file', 'implementer', 'Selected current repair evidence', payload)
        evidence.append(payload)
    return evidence


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
