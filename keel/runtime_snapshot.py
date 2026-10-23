"""Archive actual runtime source bytes, not just hashes, for isolated replay."""
import json
import platform
import sys
from pathlib import Path
from importlib import metadata

from .evaluation_protocol import implementation_hashes, file_hash


def verify_snapshot(directory):
    directory=Path(directory).resolve()
    manifest=json.loads((directory/'snapshot.json').read_text(encoding='utf-8'))
    for name,expected in manifest['implementation_sha256'].items():
        relative=Path(name)
        target=(directory/'runtime'/relative).resolve()
        if relative.is_absolute() or relative.drive or '..' in relative.parts or not target.is_relative_to(directory/'runtime'):
            raise ValueError('Snapshot path outside runtime')
        if target.is_symlink() or file_hash(target)!=expected:
            raise ValueError('Snapshot source changed: '+name)
    actual=implementation_hashes(directory/'runtime')
    if actual!=manifest['implementation_sha256']:
        raise ValueError('Snapshot runtime inventory changed')
    return manifest


def create_snapshot(root,directory):
    root=Path(root).resolve();directory=Path(directory).resolve()
    files=implementation_hashes(root)
    if not files:
        raise ValueError('No runtime implementation to snapshot')
    directory.mkdir(parents=True,exist_ok=False)
    for name,expected in files.items():
        source=root/name
        if source.is_symlink():
            raise ValueError('Runtime snapshot does not follow symlinks')
        target=directory/'runtime'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(source.read_bytes())
        if file_hash(target)!=expected:
            raise ValueError('Source changed while snapshotting: '+name)
    if implementation_hashes(root)!=files:
        raise ValueError('Runtime inventory changed while snapshotting')
    packages={}
    for name in ('pip','setuptools','mcp','tree-sitter','tree-sitter-python','lancedb','langgraph','tiktoken'):
        try:packages[name]=metadata.version(name)
        except metadata.PackageNotFoundError:packages[name]=None
    manifest={'schema_version':1,'implementation_sha256':files,
              'creator_environment':{'python':sys.version,'interpreter':sys.executable,
                                     'platform':platform.platform(),'packages':packages},
              'scope':'Actual current runtime bytes; not reconstruction of a historical success. '
                      'Environment inventory is creator observation, not a dependency lock or container archive.'}
    (directory/'snapshot.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    verify_snapshot(directory)
    return manifest
