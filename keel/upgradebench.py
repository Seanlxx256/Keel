"""UpgradeBench candidate screening. Eligibility is not benchmark readiness."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import uuid

from compass.benchmarks import canonical_repository_id, relative_path
from .core import digest

UPGRADE = re.compile(r'\b(upgrad\w*|bump\w*|migrat\w*|compatib\w*)\b', re.I)
DEPENDENCY = {'pyproject.toml', 'setup.py', 'setup.cfg', 'package.json', 'package-lock.json',
              'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock', 'pipfile', 'pipfile.lock',
              'go.mod', 'go.sum', 'cargo.toml', 'cargo.lock', 'pom.xml', 'build.gradle'}
SOURCE_SUFFIXES = {'.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java'}
DEVELOPER_TOOL = re.compile(
    r'\b(ruff|black|isort|flake8|pylint|mypy|pyright|eslint|prettier|'
    r'formatter|formatting|linter|linting|pre-commit)\b', re.I)
CI_TOOL = re.compile(r'\b(actions/|github/codeql-action|gh-action-|harden-runner)', re.I)
COMPATIBILITY = re.compile(r'\b(compatib\w*|migrat\w*)\b', re.I)
COMPATIBILITY_WAIVERS = {'fewer_than_three_changed_files', 'no_dependency_manifest_change'}


def classify_candidate(title, files):
    """Conservative triage signals, not a semantic compatibility verdict."""
    if files and all(path.startswith('.github/workflows/') for path in files):
        category, signal = 'ci_tooling', 'workflow_only_changes'
    elif CI_TOOL.search(title):
        category, signal = 'ci_tooling', 'ci_tool_title_signal'
    elif DEVELOPER_TOOL.search(title):
        category, signal = 'developer_tooling', 'developer_tool_title_signal'
    else:
        category, signal = 'unclassified_upgrade', 'manual_dependency_scope_review_required'
    return {'category': category, 'signal': signal, 'method': 'metadata_heuristic_v1',
            'runtime_compatibility_verified': False,
            'manual_override_requires_review': True}


def dependency_file(path):
    name = Path(path).name.lower()
    return name in DEPENDENCY or (name.startswith('requirements') and name.endswith(('.txt', '.in')))


def source_file(path):
    parts = path.lower().split('/')
    name = parts[-1]
    return (Path(path).suffix in SOURCE_SUFFIXES and not dependency_file(path)
            and not any(p in {'test', 'tests', 'testing', 'docs', '.github', 'vendor', 'node_modules'} for p in parts)
            and not name.startswith(('test_', 'conftest.'))
            and not any(token in name for token in ['_test.', '.test.', '.spec.']))


def screen(row):
    if not isinstance(row, dict):
        raise ValueError('Each candidate must be an object')
    repo = canonical_repository_id(row.get('repository'))
    number = row.get('number')
    if type(number) is not int or number <= 0:
        raise ValueError('PR number must be a positive integer')
    for key in ['base_commit', 'gold_commit']:
        if not isinstance(row.get(key), str) or not re.fullmatch('[0-9a-f]{40}', row[key]):
            raise ValueError('Candidate revisions require full lowercase 40-character commit SHAs')
    if row['base_commit'] == row['gold_commit']:
        raise ValueError('Base and gold revisions must differ')
    if not isinstance(row.get('title'), str) or type(row.get('merged')) is not bool:
        raise ValueError('Candidate requires title and explicit merged flag')
    if not isinstance(row.get('files'), list) or not isinstance(row.get('ci_paths'), list):
        raise ValueError('Candidate requires files and ci_paths arrays')
    files = [relative_path(path) for path in row['files']]
    ci = [relative_path(path) for path in row['ci_paths']]
    if len(files) != len(set(files)):
        raise ValueError('Duplicate changed file paths')
    reasons = []
    if not row['merged']:
        reasons.append('not_merged')
    if not UPGRADE.search(row['title']):
        reasons.append('no_upgrade_title_signal')
    if len(files) < 3:
        reasons.append('fewer_than_three_changed_files')
    if not any(dependency_file(path) for path in files):
        reasons.append('no_dependency_manifest_change')
    if not any(source_file(path) for path in files):
        reasons.append('no_non_test_source_change')
    if not any(path.startswith('.github/workflows/') and path.endswith(('.yml', '.yaml'))
               or path in {'.gitlab-ci.yml', '.travis.yml', 'Jenkinsfile'} for path in ci):
        reasons.append('no_ci_configuration_evidence')
    classification = classify_candidate(row['title'], files)
    compatibility_candidate = (bool(COMPATIBILITY.search(row['title']))
        and classification['category'] == 'unclassified_upgrade'
        and not (set(reasons) - COMPATIBILITY_WAIVERS))
    return {'id': repo.replace('/', '__') + '-' + str(number), 'repository': repo, 'number': number,
            'url': f'https://github.com/{repo}/pull/{number}', 'title': row['title'],
            'base_commit': row['base_commit'], 'gold_commit': row['gold_commit'],
            'files': sorted(files), 'ci_paths': sorted(ci), 'eligible_candidate': not reasons,
            'classification': classification,
            'main_track_candidate': not reasons and classification['category'] == 'unclassified_upgrade',
            'compatibility_review_candidate': compatibility_candidate,
            'compatibility_review': {
                'status': 'pending' if compatibility_candidate else 'not_selected',
                'waived_structural_reasons': sorted(set(reasons) & COMPATIBILITY_WAIVERS) if compatibility_candidate else [],
                'required_evidence': ['external_dependency_and_target_revision',
                    'semantic_api_change_not_only_formatting', 'same_environment_base_fail_gold_pass']
                    if compatibility_candidate else []},
            'reasons': reasons, 'benchmark_ready': False,
            'pending_checks': ['git_range_and_metadata_verification', 'curated_task_description_and_leakage_review',
                               'docker_environment_reproduction', 'base_fails_gold_passes_same_acceptance',
                               'test_collection_identity_and_environment_failure_review']}


def freeze_candidates(rows, output, *, seed=42, provenance=None):
    if not isinstance(rows, list):
        raise ValueError('Candidates must be an array')
    records, seen = [], set()
    for row in rows:
        record = screen(row)
        if record['id'] in seen:
            raise ValueError('Duplicate candidate identity')
        seen.add(record['id'])
        records.append(record)
    records.sort(key=lambda record: record['id'])
    eligible = [record for record in records if record['eligible_candidate']]
    sample_size = math.ceil(len(eligible) * .1)
    sample = sorted(eligible, key=lambda row: digest([seed, row['id']]))[:sample_size]
    classification_counts = {}
    for record in records:
        category = record['classification']['category']
        classification_counts[category] = classification_counts.get(category, 0) + 1
    compatibility = [record for record in records if record['compatibility_review_candidate']]
    report = {'schema_version': 3, 'status': 'candidate_screening_only', 'benchmark_ready': False,
              'seed': seed, 'provenance': provenance or {'origin': 'operator_local_export', 'authenticity_verified': False},
              'input_sha256': digest(rows), 'candidate_manifest_sha256': digest(records),
              'counts': {'input': len(records), 'eligible': len(eligible), 'rejected': len(records)-len(eligible)},
              'triage': {'classification_counts': classification_counts,
                         'main_track_candidates': sum(record['main_track_candidate'] for record in records),
                         'compatibility_review_candidates': len(compatibility),
                         'eligible_tooling_candidates': sum(record['eligible_candidate'] and
                             record['classification']['category'] != 'unclassified_upgrade' for record in records)},
              'manual_review': {'fraction': .1, 'sample_ids': [row['id'] for row in sample], 'status': 'pending'},
              'compatibility_review_queue': {'status': 'pending', 'review_fraction': 1.0,
                  'ids': [record['id'] for record in compatibility],
                  'scope': 'Separate exploratory pool; all entries require review, not benchmark tasks. May overlap main track.'},
              'records': records,
              'limitations': 'Metadata screening only. No repository checkout, test execution, valid task count, resolve-rate denominator, or human review completion is established.'}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'candidates.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (output / 'source.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='Local candidate JSON array; never executed')
    parser.add_argument('--output-dir', type=Path, default=Path('.keel/upgradebench') / uuid.uuid4().hex)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    rows = json.loads(args.input.read_text(encoding='utf-8-sig'))
    report = freeze_candidates(rows, args.output_dir, seed=args.seed)
    print(f'Artifacts: {args.output_dir.resolve()}')
    print(json.dumps({'counts': report['counts'], 'triage': report['triage'], 'manual_review': report['manual_review'],
                      'benchmark_ready': report['benchmark_ready']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
