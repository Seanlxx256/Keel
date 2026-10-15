"""Local preregistration checks; no inference of whether humans saw task answers."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re

from .core import digest

REGISTRY = 'examples/evaluation_development_registry.json'


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def workspace_file(root, name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '..' in Path(name).parts:
        raise ValueError('Workspace-relative file path required')
    path = (root/name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Input file must exist inside the workspace')
    return path


def registry(root):
    return json.loads(workspace_file(root, REGISTRY).read_text(encoding='utf-8'))


def canonical_repo(value, known):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
        raise ValueError('Repository must be owner/name')
    if any(part in {'.', '..'} for part in value.split('/')) or value.lower().endswith('.git'):
        raise ValueError('Canonical repository without parent segments or .git required')
    return known.get('repository_aliases', {}).get(value.lower(), value.lower())


def development_status(root, identity):
    known = registry(root)
    rows = [row for row in known['tasks'] if row['id'] == identity]
    if len(rows) != 1:
        raise ValueError('Diagnostic task must be registered before execution')
    return {'split': 'development', 'task_id': identity, 'heldout_eligible': False,
            'reason': rows[0]['reason'], 'registry_sha256': file_hash(workspace_file(root, REGISTRY))}


def implementation_hashes(root):
    files = set()
    for directory in ('keel', 'compass', 'examples', 'adapters'):
        base = root/directory
        if base.exists():
            files.update(p.relative_to(root).as_posix() for p in base.rglob('*.py'))
    for name in ('pyproject.toml', REGISTRY):
        if (root/name).is_file():
            files.add(name)
    return {name: file_hash(workspace_file(root, name)) for name in sorted(files)}


def freeze(root, plan):
    if not isinstance(plan, dict) or set(plan) != {'tasks', 'settings_file', 'operator_declared_unseen'} or plan['operator_declared_unseen'] is not True:
        raise ValueError('Plan requires tasks, settings_file and operator_declared_unseen=true')
    tasks = plan['tasks']
    if not isinstance(tasks, list) or not tasks:
        raise ValueError('A nonempty task list is required; no empty held-out claim')
    known = registry(root)
    seen_ids, seen_prs = set(), set()
    dev_repos = {canonical_repo(row['repository'], known) for row in known['tasks']}
    dev_ids = {row['id'] for row in known['tasks']}
    entries = []
    for row in tasks:
        if not isinstance(row, dict) or set(row) != {'id', 'repository', 'pr', 'task_file'}:
            raise ValueError('Task requires id, repository, pr and task_file')
        identity, number = row['id'], row['pr']
        repo = canonical_repo(row['repository'], known)
        if not isinstance(identity, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,120}', identity) or type(number) is not int or number <= 0:
            raise ValueError('Invalid task ID or PR number')
        if identity in seen_ids or (repo, number) in seen_prs:
            raise ValueError('Duplicate task/PR; repetitions are not new coverage')
        if identity in dev_ids or repo in dev_repos:
            raise ValueError('Development task or repository cannot enter this repository-disjoint evaluation')
        seen_ids.add(identity)
        seen_prs.add((repo, number))
        path = workspace_file(root, row['task_file'])
        entries.append({**row, 'repository': repo, 'task_sha256': file_hash(path)})
    settings = workspace_file(root, plan['settings_file'])
    # Do not copy unknown configuration contents (which may contain credentials).
    payload = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
        'protocol': 'repository-disjoint-v1', 'tasks': sorted(entries, key=lambda row: row['id']),
        'settings_file': plan['settings_file'], 'settings_sha256': file_hash(settings),
        'implementation_sha256': implementation_hashes(root), 'operator_declared_unseen': True,
        'coverage_status': 'preregistered_only', 'benchmark_ready': False,
        'limitations': 'Local hashes bind declared files, not human exposure, task validity, external model weights or authentic timestamps. No model executions or scores.'}
    return {**payload, 'protocol_sha256': digest(payload)}


def verify(root, frozen):
    payload = {key: value for key, value in frozen.items() if key != 'protocol_sha256'}
    if frozen.get('protocol_sha256') != digest(payload):
        raise ValueError('Frozen manifest digest differs')
    if frozen.get('protocol') != 'repository-disjoint-v1':
        raise ValueError('Unsupported evaluation protocol')
    if implementation_hashes(root) != frozen['implementation_sha256']:
        raise ValueError('Implementation, registry or source file set changed after freeze')
    if file_hash(workspace_file(root, frozen['settings_file'])) != frozen['settings_sha256']:
        raise ValueError('Settings changed after freeze')
    for row in frozen['tasks']:
        if file_hash(workspace_file(root, row['task_file'])) != row['task_sha256']:
            raise ValueError('Task input changed after freeze')
    return {'matched': True, 'protocol_sha256': frozen['protocol_sha256'],
            'tasks': len(frozen['tasks']), 'coverage_status': 'preregistered_only', 'benchmark_ready': False}


def verify_results(root, frozen, results):
    verify(root, frozen)
    if (results.get('protocol_sha256') != frozen['protocol_sha256'] or
        results.get('settings_sha256') != frozen['settings_sha256'] or
        results.get('implementation_sha256') != frozen['implementation_sha256'] or
        results.get('evaluation_split') != 'independent' or results.get('prepared_only') is not False):
        raise ValueError('Results must identify the frozen protocol/settings/implementation and independent execution')
    rows = results.get('records')
    if not isinstance(rows, list):
        raise ValueError('Result records required')
    expected = {row['id']: row for row in frozen['tasks']}
    observed = set()
    passed = errors = 0
    for row in rows:
        identity = row.get('id')
        if identity not in expected or identity in observed:
            raise ValueError('Unexpected or repeated task result')
        observed.add(identity)
        if row.get('task_sha256') != expected[identity]['task_sha256'] or type(row.get('attempt')) is not int or row['attempt'] != 1:
            raise ValueError('Independent summary requires frozen inputs and first attempts only')
        if (type(row.get('passed')) is not bool or type(row.get('executed')) is not bool or
            row.get('status') not in {'completed', 'environment_error', 'runtime_error'}):
            raise ValueError('Terminal typed outcomes required')
        if row['passed'] and (row['status'] != 'completed' or not row['executed']):
            raise ValueError('A pass must be completed and executed')
        passed += int(row['passed'])
        errors += int(row['status'] in {'environment_error', 'runtime_error'})
    if observed != expected.keys():
        raise ValueError('Every planned task must remain in results, including failures')
    return {'planned': len(expected), 'passed': passed, 'errors': errors,
            'benchmark_ready': False, 'scope': 'Manifest consistency only; no execution authenticity, statistical independence or acceptance correctness proof'}
