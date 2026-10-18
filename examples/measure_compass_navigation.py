"""Offline navigation smoke measurement; byte size is not retrieval quality."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.index import build_index, RepositoryIndex
from compass.retrieval import Retriever


def measure(repo, files, output):
    repo = repo.resolve(strict=True)
    sources = {}
    for name in files:
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Select repository-relative source paths')
        path = (repo/name).resolve(strict=True)
        if not path.is_relative_to(repo) or path.suffix != '.py':
            raise ValueError('Select contained Python source files')
        sources[name] = path.read_bytes()
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output/'snapshot'
    snapshot.mkdir()
    for name, source in sources.items():
        target = snapshot/name
        # Resolve again to reject absolute names even when they referred into repo.
        if not target.resolve().is_relative_to(snapshot.resolve()):
            raise ValueError('Snapshot paths must be relative')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source)
    build_index(snapshot, parser='python-ast')
    rows = []
    with RepositoryIndex(snapshot) as index:
        for name, source in sources.items():
            offset, pages = 0, []
            while offset is not None:
                page = index.overview(name, depth=1, limit=100, offset=offset)
                pages.append(page)
                offset = page['next_offset']
            definitions = [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            location = f'{name}:{min(n.lineno for n in definitions)}' if definitions else None
            found = Retriever(index).retrieve(location) if location else None
            rows.append({'file': name, 'source_sha256': hashlib.sha256(source).hexdigest(),
                'source_bytes': len(source), 'outline_json_bytes': sum(len(json.dumps(p, ensure_ascii=False).encode()) for p in pages),
                'outline_symbols': sum(len(p['results']) for p in pages), 'outline_pages': len(pages),
                'location_query': location, 'location_tier': found['tier'] if found else None,
                'location_model_calls': found['usage']['model_calls'] if found else None})
    result = {'model_calls': 0, 'records': rows,
        'scope': 'Development source outline/navigation smoke; outlines omit bodies and are not equivalent source context. No recall or repair improvement claim.'}
    (output/'measurement.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--files', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(measure(args.repo, args.files, args.output), indent=2))
