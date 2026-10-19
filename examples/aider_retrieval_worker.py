"""Measure installed Aider's native ranked tags, not a reimplementation of PageRank."""
import argparse
import ast
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json


def source_regions(path):
    """Independent Python AST range adapter; no Compass index or labels."""
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (SyntaxError, UnicodeError):
        return {}
    return {(node.name, node.lineno-1): (min([node.lineno]+[
        d.lineno for d in node.decorator_list]), node.end_lineno)
        for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def tag_candidates(tags, root):
    result, seen, parsed = [], set(), {}
    skipped = 0
    for tag in tags:
        # Aider can append file-only tuples; disclose rather than invent a span.
        if not hasattr(tag, 'line') or tag.line < 0:
            skipped += 1
            continue
        path = (root/tag.rel_fname).resolve(strict=True)
        if not path.is_relative_to(root) or path.suffix != '.py' or path.is_symlink():
            raise ValueError('Unsafe ranked tag path')
        if path not in parsed:
            parsed[path] = source_regions(path)
        region = parsed[path].get((tag.name, tag.line))
        if region is None:
            skipped += 1
            continue
        key = (path.relative_to(root).as_posix(), *region)
        if key not in seen:
            result.append(dict(path=key[0], start_line=key[1], end_line=key[2]))
            seen.add(key)
        if len(result) == 100:
            break
    return result, skipped


def retrieve(config):
    from aider.repomap import RepoMap
    root = Path(config['repo']).resolve(strict=True)
    listed = subprocess.run(['git', '-c', 'safe.directory='+str(root), 'ls-files', '--stage', '-z'],
        cwd=root, capture_output=True, check=True, timeout=30).stdout
    files = []
    for entry in listed.split(b'\0'):
        if not entry:
            continue
        attrs, name = entry.split(b'\t', 1)
        mode, _, stage = attrs.decode().split()
        relative = name.decode('utf-8')
        path = root/relative
        if stage != '0':
            raise ValueError('Unmerged source entry')
        if mode in ('100644', '100755') and path.suffix == '.py':
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Unsafe source file')
            files.append(str(path.resolve(strict=True)))
    before = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files}
    class IO:
        def read_text(self, filename):
            return Path(filename).read_text(encoding='utf-8', errors='replace')
        def tool_output(self, text):
            print(text, flush=True)
        tool_warning = tool_output
        tool_error = tool_output
    class ReadOnlyRepoMap(RepoMap):
        def load_tags_cache(self):
            # Native tag extraction/ranking unchanged; keep cache outside snapshots.
            self.TAGS_CACHE = {}
    mapper = ReadOnlyRepoMap(root=str(root), io=IO(), verbose=False)
    identifiers = set(re.findall(r'\b[A-Za-z_][A-Za-z_0-9]*\b', config['query']))
    mentioned = {Path(p).relative_to(root).as_posix() for p in files
                 if Path(p).relative_to(root).as_posix() in config['query']}
    ranked = mapper.get_ranked_tags([], files, mentioned, identifiers)
    candidates, skipped = tag_candidates(ranked, root)
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != v for p, v in before.items()):
        raise ValueError('Source changed during Aider retrieval')
    return dict(status='ok', version=metadata.version('aider-chat'), candidates=candidates,
        source_files=len(files), skipped_tags=skipped, generation_model_calls=0,
        repomap_sha256=hashlib.sha256(Path(sys.modules['aider.repomap'].__file__).read_bytes()).hexdigest(),
        source_manifest_sha256=hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
        adapter='Native Aider get_ranked_tags; empty chat files; query-only identifier hints; '
        'in-memory tag cache; independent AST spans; shared 100-line/32-line packing. '
        'This is a ranking-component comparison, not full Aider chat or its rendered token-budgeted map.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    try:
        result = retrieve(json.loads(args.input.read_text(encoding='utf-8')))
    except ModuleNotFoundError as error:
        result = dict(status='unavailable', error_type=type(error).__name__, error=str(error))
    except Exception as error:
        result = dict(status='failed', error_type=type(error).__name__, error=str(error)[:1000])
    result['seconds'] = time.monotonic()-started
    atomic_json(args.output, result)
