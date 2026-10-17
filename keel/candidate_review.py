"""Uniform source-only curation gates; never establishes a runnable repair task."""
import ast
import hashlib
import subprocess

from compass.benchmarks import check_snapshot, relative_path
from .upgradebench import source_file


def compare_python(before, after):
    record = {'base_sha256': hashlib.sha256(before).hexdigest() if before is not None else None,
              'gold_sha256': hashlib.sha256(after).hexdigest() if after is not None else None}
    trees, runtime_trees = [], []
    for source in (before, after):
        if source is None:
            trees.append(None)
            runtime_trees.append(None)
            continue
        try:
            trees.append(ast.dump(ast.parse(source, type_comments=True), include_attributes=False))
            runtime_trees.append(ast.dump(ast.parse(source, type_comments=False), include_attributes=False))
        except (SyntaxError, ValueError, UnicodeError):
            return {**record, 'status': 'unsupported_python_syntax', 'ast_changed': None, 'runtime_ast_changed': None}
    return {**record, 'status': 'compared', 'ast_changed': trees[0] != trees[1],
            'runtime_ast_changed': runtime_trees[0] != runtime_trees[1]}


def review_sources(row, base, gold):
    from examples.run_starlette_upgrade_task import inventory
    check_snapshot(base, row['base_commit'])
    check_snapshot(gold, row['gold_commit'])
    raw = subprocess.run(['git', '-c', f'safe.directory={gold.as_posix()}', '-C', str(gold),
        'cat-file', '-p', row['gold_commit']], check=True, capture_output=True, text=True, timeout=15).stdout
    parents = [line.split()[1] for line in raw.split('\n\n', 1)[0].splitlines() if line.startswith('parent ')]
    if not parents or parents[0] != row['base_commit']:
        raise ValueError('Pinned merge first parent mismatch')
    left, right = inventory(base), inventory(gold)
    changed = sorted(name for name in left.keys() | right.keys() if left.get(name) != right.get(name))
    actual_sources = sorted(name for name in changed if source_file(name))
    expected = sorted(relative_path(name) for name in row['source_files_curator_only'])
    if actual_sources != expected:
        raise ValueError('Actual source diff differs from shortlisted file list')
    comparisons = []
    for name in actual_sources:
        if not name.endswith('.py'):
            raise ValueError('Python-only source review')
        before, after = base/name, gold/name
        comparisons.append({'path': name, **compare_python(before.read_bytes() if before.is_file() else None,
                                                          after.read_bytes() if after.is_file() else None)})
    if any(row['ast_changed'] is None for row in comparisons):
        status = 'unsupported_python_syntax'
    elif not any(row['ast_changed'] for row in comparisons):
        status = 'excluded_no_python_ast_change'
    elif not any(row['runtime_ast_changed'] for row in comparisons):
        status = 'excluded_type_comments_only'
    else:
        status = 'needs_environment_reproduction'
    return {'status': status, 'files': comparisons, 'changed_files_curator_only': changed,
        'first_parent_verified': True, 'benchmark_ready': False,
        'limitations': 'AST comparison is a screening rule, not semantic equivalence proof. No dependency migration, target environment, base-fail/gold-pass or model repair verified.'}
