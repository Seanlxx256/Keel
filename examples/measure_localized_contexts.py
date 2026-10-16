"""Offline exhaustive single-file/single-function capacity checks; not localization quality."""
import argparse
import ast
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.audit import protected_path
from keel.localization import selection_request, symbol_structure, ANCHOR_INSTRUCTION
from keel.proposals import source_evidence, located_source_evidence, proposal_request
from examples.run_starlette_upgrade_task import inventory


def inspect(repo, cap=12000):
    repo = repo.resolve(strict=True)
    before = inventory(repo)
    goal = 'Repair a dependency compatibility issue in this repository.'
    rows = []
    for name in sorted(before):
        if not name.endswith('.py') or protected_path(name):
            continue
        path = (repo/name).resolve()
        if not path.is_relative_to(repo) or path.stat().st_nlink > 1:
            continue
        row = {'path': name, 'anchors': [], 'definitions': []}
        rows.append(row)
        raw = path.read_bytes()
        if len(raw) > 1_000_000:
            row['error'] = 'read_file supports files up to 1 MB'
            continue
        try:
            text = raw.decode('utf-8')
            tree = ast.parse(text)
        except (UnicodeError, SyntaxError) as error:
            row['error'] = type(error).__name__
            continue
        kwargs = {'stage': 'anchor-selection', 'data': {'structure': [symbol_structure(name, text)]},
            'keys': ('locations',), 'instruction': ANCHOR_INSTRUCTION}
        size = selection_request(goal, {'max_context_bytes': sys.maxsize}, **kwargs)[2]
        row.update(symbol_request_bytes=size, symbol_request_fits=size <= cap)
        anchors = sorted({node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))})
        for anchor in anchors:
            evidence = source_evidence(name, text, [anchor])
            size = proposal_request(goal, [name], [evidence], {'max_context_bytes': sys.maxsize})[2]
            row['anchors'].append({'query': anchor, 'request_bytes': size, 'fits': size <= cap})
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            evidence = located_source_evidence(name, text, [node.lineno])
            size = proposal_request(goal, [name], [evidence], {'max_context_bytes': sys.maxsize})[2]
            row['definitions'].append({'name': node.name, 'line': node.lineno, 'request_bytes': size, 'fits': size <= cap})
    anchors = [a for row in rows for a in row['anchors']]
    definitions = [a for row in rows for a in row['definitions']]
    return {'repo': str(repo), 'cap_bytes': cap, 'new_model_calls': 0,
        'source_unchanged': inventory(repo) == before,
        'input_inventory': before, 'files': rows,
        'summary': {'files': len(rows), 'files_with_errors': sum('error' in r for r in rows),
            'single_file_symbol_requests_fit': sum(r.get('symbol_request_fits', False) for r in rows),
            'single_function_requests': len(anchors), 'single_function_requests_fit': sum(a['fits'] for a in anchors),
            'exact_definition_requests': len(definitions), 'exact_definition_requests_fit': sum(a['fits'] for a in definitions)},
        'limitations': 'Exhaustive hypothetical single-file/function-name selections, not model predictions. Multi-file and multi-anchor contexts can be larger. Generic goal, structured requests, no provider calls or repair outcomes. Scan cost is offline analysis, not runtime budget accounting.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists')
    reports = [inspect(repo) for repo in args.repo]
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(reports, stream, indent=2)
    print(json.dumps([{k: r[k] for k in ('repo', 'summary', 'source_unchanged', 'new_model_calls')} for r in reports], indent=2))


if __name__ == '__main__':
    main()
