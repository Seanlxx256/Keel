"""Trace a removed import through a bounded pinned file history; no Docker/model."""
import argparse
import base64
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import canonical_repository_id
from examples.mine_upgradebench import GitHub
from keel.import_evidence import imported_symbol


def source_at(fetch, repo, path, revision):
    data = fetch(f'/repos/{repo}/contents/{quote(path, safe="/")}?' + urlencode({'ref': revision}))
    if (not isinstance(data, dict) or data.get('type') != 'file' or data.get('encoding') != 'base64'
            or type(data.get('size')) is not int or not 0 <= data['size'] <= 300000):
        raise ValueError('Bounded source file required')
    source = base64.b64decode(data['content'], validate=False)
    if len(source) != data['size']:
        raise ValueError('Source content size mismatch')
    import hashlib
    blob = hashlib.sha1(b'blob '+str(len(source)).encode()+b'\0'+source).hexdigest()
    if blob != data.get('sha'):
        raise ValueError('Source Git blob hash mismatch')
    return source


def trace(fetch, repo, revision, path, module, symbol, limit=20, record=None):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('History limit must be 1..20')
    repo = canonical_repository_id(repo)
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Immutable starting revision required')
    if (not path.endswith('.py') or path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/'))
            or '\\' in path or ':' in path):
        raise ValueError('Repository-relative Python path required')
    starting = imported_symbol(source_at(fetch, repo, path, revision), module, symbol)
    rows = fetch(f'/repos/{repo}/commits?' + urlencode({'sha': revision, 'path': path, 'per_page': limit, 'page': 1}))
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError('Invalid history response')
    checked = []
    for row in rows:
        sha = row.get('sha')
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{40}', sha):
            raise ValueError('Invalid history commit')
        detail = fetch(f'/repos/{repo}/commits/{sha}')
        parents = detail.get('parents', [])
        if detail.get('sha') != sha or not parents:
            raise ValueError('Missing matching commit or first parent')
        parent = parents[0].get('sha', '')
        if not re.fullmatch('[0-9a-f]{40}', parent):
            raise ValueError('Invalid immutable parent')
        # This is a bounded search hint; complete pinned source is the actual evidence.
        files = [f for f in detail.get('files', []) if f.get('filename') == path]
        patch = '\n'.join(f.get('patch', '') for f in files)
        if symbol not in patch or module not in patch:
            checked.append({'commit': sha, 'status': 'no_matching_import_patch_hint'})
            if record:
                record(checked)
            continue
        before = imported_symbol(source_at(fetch, repo, path, parent), module, symbol)
        after = imported_symbol(source_at(fetch, repo, path, sha), module, symbol)
        checked.append({'commit': sha, 'parent': parent, 'before_imports': before, 'after_imports': after})
        if record:
            record(checked)
        if before and not after:
            return {'status': 'static_import_removal_found', 'repository': repo,
                    'base_commit': parent, 'gold_commit': sha, 'starting_revision_imports': starting,
                    'checked': checked, 'benchmark_ready': False, 'model_calls': 0,
                    'limitations': 'New curator history investigation, not replacement of PR 813 or a repair score. Static removal does not prove runtime transition, linked issue resolution, first-parent reachability across merge traversal, or independent task validity.'}
    return {'status': 'not_found_within_bound', 'checked': checked, 'starting_revision_imports': starting,
            'benchmark_ready': False, 'model_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--path', required=True)
    parser.add_argument('--module', required=True)
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'plan.json').write_text(json.dumps({k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}, indent=2), encoding='utf-8')
    api = GitHub(args.output/'responses')
    def checkpoint(rows):
        (args.output/'checked.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    try:
        report = trace(api.get, args.repository, args.revision, args.path, args.module, args.symbol, record=checkpoint)
    except (ValueError, OSError, KeyError, SyntaxError, TypeError) as error:
        report = {'status': 'history_error', 'error': f'{type(error).__name__}: {error}', 'benchmark_ready': False, 'model_calls': 0}
    (args.output/'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 1 if report['status'] == 'history_error' else 0


if __name__ == '__main__':
    raise SystemExit(main())
