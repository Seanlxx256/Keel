"""Evaluation-only corpus eligibility checks; never supply labels to retrievers."""
from pathlib import Path
from .index import source_files

POLICY = 'python-reference-scope-v1'


def reference_scope(instance):
    """Cheap necessary scope check, not proof of parser/index completeness."""
    root = Path(instance['repo']).resolve(strict=True)
    inventory = {name:path for name,path in source_files(root)}
    blocked = []
    for name in sorted(set(instance['core_files'])):
        path = inventory.get(name)
        if path is None:
            blocked.append(dict(path=name,reason='outside_declared_python_corpus'))
        elif path.stat().st_size > 1_000_000:
            blocked.append(dict(path=name,reason='exceeds_index_file_size_limit'))
    return dict(policy=POLICY,eligible=not blocked,blocked=blocked,
        checked_reference_files=len(set(instance['core_files'])),
        scope='Evaluation-only eligibility. No reference ranges removed; no inputs passed to adapters. '
              'Passing is necessary, not sufficient for final index coverage validation.')
