"""Import frozen candidate modules in their real package, retaining dependencies.

Used in a fresh diagnostic interpreter, not as a patch or general hot-reloader.
"""
from contextlib import contextmanager
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
from pathlib import Path
import sys


@contextmanager
def candidate_context(root, modules):
    root = Path(root).resolve(strict=True)
    entries = {}
    for name, row in modules.items():
        if not isinstance(name, str) or not name or any(not part.isidentifier() for part in name.split('.')):
            raise ValueError('Candidate module must have a qualified Python name')
        path = (root/row['path']).resolve(strict=True)
        if not path.is_relative_to(root) or path.suffix != '.py':
            raise ValueError('Candidate module source escapes the snapshot')
        entries[name] = (path, row['sha256'])
    roots = {name.split('.')[0] for name in entries}
    if any(name.split('.')[0] in roots for name in sys.modules):
        raise RuntimeError('Candidate package already imported; use a fresh interpreter')
    loaded = []
    original_search_path = list(sys.path)

    def snapshot_search_entry(value):
        if not isinstance(value, str):
            return False
        try:
            return Path(value or Path.cwd()).resolve().is_relative_to(root)
        except (OSError, RuntimeError):
            return False

    class Loader(importlib.abc.Loader):
        def __init__(self, name, path, sha):
            self.name, self.path, self.sha = name, path, sha

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            raw = self.path.read_bytes()
            actual = hashlib.sha256(raw).hexdigest()
            if actual != self.sha:
                raise RuntimeError('Candidate source hash changed before import')
            module.__file__ = str(self.path)
            record = {'module': self.name, 'path': str(self.path), 'sha256': actual, 'status':'loading'}
            loaded.append(record)
            try:
                exec(compile(raw, str(self.path), 'exec'), module.__dict__)
            except BaseException:
                record['status'] = 'failed'
                raise
            else:
                record['status'] = 'executed'

    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname not in entries:
                return None
            source, sha = entries[fullname]
            locations = None
            if source.name == '__init__.py':
                original = importlib.machinery.PathFinder.find_spec(fullname, path)
                locations = list(dict.fromkeys([str(source.parent),
                    *(original.submodule_search_locations or [] if original else [])]))
            return importlib.util.spec_from_file_location(fullname, source,
                loader=Loader(fullname, source, sha), submodule_search_locations=locations)

    finder = Finder()
    # A thin mounted tree can form a namespace package before a PEP 660 finder
    # at the end of meta_path sees the real installed parent. Candidate files
    # are served explicitly by our finder, never via cwd/sys.path discovery.
    sys.path[:] = [entry for entry in sys.path if not snapshot_search_entry(entry)]
    sys.meta_path.insert(0, finder)
    try:
        yield loaded
    finally:
        sys.meta_path.remove(finder)
        sys.path[:] = original_search_path
        for name in list(sys.modules):
            if name.split('.')[0] in roots:
                del sys.modules[name]


def module_manifest(root, files):
    root = Path(root).resolve(strict=True)
    result = {}
    for name in files:
        path = (root/name).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError('Candidate source escapes the snapshot')
        if path.suffix != '.py':
            continue
        parts = list(Path(name).with_suffix('').parts)
        if parts[-1] == '__init__':
            parts.pop()
        if not parts or any(not part.isidentifier() for part in parts):
            continue
        result['.'.join(parts)] = {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return result
