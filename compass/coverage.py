"""Explicit corpus eligibility; never rewrite an incomplete index as complete."""
import ast
import hashlib
import platform


POLICIES = ('strict', 'valid-python')


def index_coverage(index, policy='strict'):
    if policy not in POLICIES:
        raise ValueError('Unknown index coverage policy')
    result = {'policy': policy, 'index_complete': index.metadata['complete'],
              'eligible': bool(index.metadata['complete']), 'excluded': [], 'blocked': []}
    if policy == 'strict' or result['eligible']:
        return result
    index.require_fresh()
    diagnostics = index.metadata.get('diagnostics', [])
    if not diagnostics:
        result['blocked'].append({'reason': 'Incomplete index without diagnostic inventory'})
        return result
    # The permissive scope is explicit and label-independent. Both grammars must
    # reject these exact bytes; valid source lost by an extractor remains blocked.
    from tree_sitter import Language, Parser
    import tree_sitter_python
    parser = Parser(Language(tree_sitter_python.language()))
    for diagnostic in diagnostics:
        name = diagnostic['path']
        row = index.db.execute('SELECT status,content_hash FROM files WHERE path=?', (name,)).fetchone()
        path = index.root/name
        evidence = {'path': name, 'diagnostic': diagnostic['error'], 'python': platform.python_version()}
        try:
            if row is None or row['status'] != 'parse_error' or path.is_symlink() or not path.resolve().is_relative_to(index.root):
                raise ValueError('Not a regular parse-error source within the index root')
            raw = path.read_bytes()
            evidence['sha256'] = hashlib.sha256(raw).hexdigest()
            if evidence['sha256'] != row['content_hash']:
                raise ValueError('Diagnostic source changed')
            try:
                ast.parse(raw.decode('utf-8'), filename=name)
            except SyntaxError as error:
                evidence.update(line=error.lineno, reason='invalid_python_source')
                if parser.parse(raw).root_node.has_error:
                    evidence['checks'] = ['python_ast_rejects', 'tree_sitter_rejects', 'source_hash_matches']
                    result['excluded'].append(evidence)
                    continue
            raise ValueError('Source invalidity not independently confirmed by both grammars')
        except (OSError, UnicodeError, ValueError, RecursionError) as error:
            result['blocked'].append({**evidence, 'reason': str(error)})
    result['eligible'] = not result['blocked']
    result['scope'] = 'Valid Python corpus only; excluded source stays in diagnostics; not strict full-corpus coverage'
    return result
