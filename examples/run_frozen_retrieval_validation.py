"""Freeze new retrieval tasks, then execute unchanged baseline/reranker/fusion arms."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import load_swe_instance
from compass.index import RepositoryIndex, build_index
from compass.preparation import PublicData, SWE_DATASET, VERIFIED_DATASET, prepare_snapshot, select_instances
from compass.retrieval import Routing
from compass.sweep import run_swe_sweep
from compass.vectors import OllamaEmbedder
from compass.progress import atomic_json
from compass.coverage import POLICIES, index_coverage
from keel.core import Limits
from examples.compare_retrieval_alternatives import run as compare, score
from examples.evaluate_retrieval_reranker import evaluate
from examples.replay_retrieval_fusion import replay


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exposure_registry(project):
    # Deliberately exclude planned as well as measured tasks; never drop a
    # previous failure from the exposure set simply because it lacks a score.
    names = {'plan.json', 'result.json', 'evaluation.json', 'comparison.json',
             'fusion.json', 'diagnosis.json', 'task.json', 'manifest.json'}
    files = [project/'examples/evaluation_development_registry.json']
    for directory in ('.keel/swe-public', '.keel/swe-independent', '.keel/swebench',
                      '.keel/retrieval-validation', '.keel/structural-validation', 'docs/evaluations'):
        root = project/directory
        if root.exists():
            files.extend(p for p in root.rglob('*.json') if p.name in names or directory == 'docs/evaluations')
    identifiers, receipts = set(), {}
    def visit(value):
        if isinstance(value, dict):
            for key, entry in value.items():
                if key in ('id', 'instance', 'instance_id', 'task_id') and isinstance(entry, str) and \
                        re.fullmatch(r'[\w.-]+__[\w.-]+-\d+', entry):
                    identifiers.add(entry)
                elif isinstance(entry, (dict, list)):
                    visit(entry)
        elif isinstance(value, list):
            for entry in value:
                visit(entry)
    for path in sorted(set(files)):
        if not path.is_file():
            continue
        value = json.loads(path.read_text(encoding='utf-8'))
        receipts[str(path.resolve())] = digest(path)
        visit(value)
    return identifiers, receipts


def freeze(project, output, *, count=5, seed=20261018):
    output.mkdir(parents=True, exist_ok=False)
    excluded, receipts = exposure_registry(project)
    data = PublicData(project/'.keel/datasets/swe', offline=True)
    swe, swe_source = data.dataset(SWE_DATASET, 'train')
    verified, verified_source = data.dataset(VERIFIED_DATASET, 'test')
    selected, selection = select_instances(swe, verified, count=count, seed=seed, exclude_instances=excluded)
    cache = project/'.keel/retrieval-reranking/reranker-model-cache'
    revision_path = cache/'models--cross-encoder--ms-marco-MiniLM-L6-v2/refs/main'
    revision = revision_path.read_text().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('A full cached reranker revision is required before freezing')
    environment_source = project/'.keel/retrieval-alternatives/v4/task-1/query-only.json'
    pyright_command = json.loads(environment_source.read_text(encoding='utf-8')).get('pyright_command')
    tasks = []
    for number, item in enumerate(selected, 1):
        directory = output/f'task-{number}'
        directory.mkdir()
        path = directory/'instance.jsonl'
        path.write_text(json.dumps(item['record'])+'\n', encoding='utf-8')
        tasks.append({'instance_id': item['record']['instance_id'], 'repository': item['repository_id'],
            'base_commit': item['record']['base_commit'], 'dataset': str(path.resolve()), 'dataset_sha256': digest(path)})
    for path, expected in receipts.items():
        if digest(Path(path)) != expected:
            raise ValueError('Exposure registry changed while freezing tasks')
    implementations = [Path(__file__), Path(__file__).with_name('compare_retrieval_alternatives.py'),
        Path(__file__).with_name('serena_retrieval_worker.py'), Path(__file__).with_name('cocoindex_retrieval_worker.py'),
        Path(__file__).with_name('evaluate_retrieval_reranker.py'), Path(__file__).with_name('reranker_worker.py'),
        Path(__file__).with_name('replay_retrieval_fusion.py'), project/'compass/retrieval.py',
        project/'compass/benchmarks.py', project/'compass/index.py', project/'compass/sweep.py',
        project/'compass/lexical.py', project/'compass/vectors.py', project/'compass/preparation.py',
        project/'keel/experience.py', project/'keel/tool_recovery.py', project/'keel/ipc.py',
        project/'compass/coverage.py', project/'compass/progress.py', Path(__file__).with_name('build_validation_index.py')]
    plan = {'kind': 'frozen new-task retrieval validation', 'tasks': tasks, 'sources': [swe_source, verified_source],
        'seed': seed, 'selection': selection, 'excluded_instance_ids': sorted(excluded),
        'exposure_receipts_sha256': receipts, 'implementation_sha256': {str(p.resolve()): digest(p) for p in implementations},
        'policy': {'line_budget': 100, 'symbol_line_cap': 32, 'arms': ['baseline', 'reranked', 'equal_weight_rrf_60'],
            'compass_ranking': 'code-aware', 'compass_embedding': 'keel-embed', 'compass_vector_store': 'sqlite',
            'reranker_model': 'cross-encoder/ms-marco-MiniLM-L6-v2', 'reranker_revision': revision,
            'reranker_model_cache': str(cache), 'max_pair_tokens': 512, 'batch_size': 8, 'device': 'cpu',
            'cocoindex_embedding': 'Snowflake/snowflake-arctic-embed-xs',
            'serena_identifier_queries': 8, 'serena_matches_per_query': 100, 'pyright_command': pyright_command},
        'benchmark_ready': False, 'limitations': 'New relative to recorded local experiments, not verified training-unseen. '
            'Seeded selection retains existing small-repository preference and Python/read-core eligibility. '
            'No replacement of failed tasks. One run per task; no significance or agent-repair claim. '
            'Package/embedding identity must be reported; only reranker weight revision is explicitly pinned.'}
    (output/'plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    (output/'plan.sha256').write_text(digest(output/'plan.json')+'\n', encoding='utf-8')
    return plan


def verify_plan(path, *, check_implementation=True):
    if digest(path) != path.with_suffix('.sha256').read_text().strip():
        raise ValueError('Plan digest mismatch')
    plan = json.loads(path.read_text(encoding='utf-8'))
    if len({t['instance_id'] for t in plan['tasks']}) != len(plan['tasks']) or \
            {t['instance_id'] for t in plan['tasks']} & set(plan['excluded_instance_ids']):
        raise ValueError('Duplicate or previously exposed selected task')
    for task in plan['tasks']:
        if digest(Path(task['dataset'])) != task['dataset_sha256']:
            raise ValueError('Frozen task data changed')
    for name, expected in plan['implementation_sha256'].items():
        if check_implementation and digest(Path(name)) != expected:
            raise ValueError('Frozen implementation changed: '+name)
    return plan


def resume_plan(project, parent, previous, output, *, coverage_policy=None):
    plan = verify_plan(parent, check_implementation=False)
    prior = json.loads((previous/'validation.json').read_text(encoding='utf-8'))
    if prior['plan_sha256'] != digest(parent):
        raise ValueError('Resume run does not belong to supplied plan')
    allowed = {project/'compass/index.py', Path(__file__).resolve(),
               Path(__file__).with_name('compare_retrieval_alternatives.py'),
               Path(__file__).with_name('evaluate_retrieval_reranker.py'),
               Path(__file__).with_name('reranker_worker.py'),
               Path(__file__).with_name('build_validation_index.py'),
               Path(__file__).with_name('cocoindex_retrieval_worker.py'), project/'keel/experience.py',
               Path(__file__).with_name('serena_retrieval_worker.py'), project/'keel/tool_recovery.py', project/'keel/ipc.py',
               project/'compass/sweep.py', project/'compass/coverage.py', project/'compass/progress.py'}
    allowed.add(project/'compass/vectors.py')
    changes = {}
    for name, expected in plan['implementation_sha256'].items():
        current = digest(Path(name))
        if current != expected:
            if Path(name) not in allowed:
                raise ValueError('Unreviewed implementation change in resume: '+name)
            changes[name] = {'before': expected, 'after': current}
    plan['resume_revision'] = {'parent_plan': str(parent), 'parent_sha256': digest(parent),
        'previous_run': str(previous), 'previous_report_sha256': digest(previous/'validation.json'),
        'implementation_changes': changes,
        'scope': 'Explicit infrastructure repair/resume; task data and ranking policy retained. Not an unchanged implementation run.'}
    if coverage_policy is not None:
        if coverage_policy not in POLICIES:
            raise ValueError('Unknown coverage policy')
        before = plan['policy'].get('index_coverage', 'strict')
        plan['policy']['index_coverage'] = coverage_policy
        if before != coverage_policy:
            plan['resume_revision']['policy_changes'] = {'index_coverage': {'before': before, 'after': coverage_policy}}
            plan['resume_revision']['scope'] = ('Explicit corpus-coverage protocol amendment; task data and ranking unchanged. '
                'Not an unchanged strict full-corpus result; original failures retained.')
    plan['implementation_sha256'] = {name: digest(Path(name)) for name in plan['implementation_sha256']}
    worker = Path(__file__).with_name('build_validation_index.py')
    plan['implementation_sha256'][str(worker)] = digest(worker)
    experience = project/'keel/experience.py'
    plan['implementation_sha256'][str(experience)] = digest(experience)
    coverage = project/'compass/coverage.py'
    plan['implementation_sha256'][str(coverage)] = digest(coverage)
    for helper in ('tool_recovery.py', 'ipc.py'):
        path = project/'keel'/helper
        plan['implementation_sha256'][str(path)] = digest(path)
    helper = project/'compass/progress.py'
    plan['implementation_sha256'][str(helper)] = digest(helper)
    coco = Path(__file__).with_name('cocoindex_retrieval_worker.py')
    if str(coco) in changes:
        previous_hash = changes[str(coco)]['before']
        if previous_hash not in {'3af42ee7548752cd2a49ac3af2a75d52b7e44062b227ac0d5b526a6b80690590',
                                 'a6da6287516933443e4dd939343066d49ec19dfbf4725b0666cbdf7a1e6ef147',
                                 '939f440795ba1881e1f0ddfb2f70995ca2e0c980006ce56004d12d9d4614f698'}:
            raise ValueError('CocoIndex migration requires explicit predecessor review')
        compatibility = plan.setdefault('compatible_worker_hashes', {})
        compatibility.setdefault(coco.name, []).append(previous_hash)
    # Reviewed exact predecessors: successful executions did not exercise the
    # newly added failure branches. Do not authorize arbitrary future workers.
    serena = Path(__file__).with_name('serena_retrieval_worker.py')
    if str(serena) in changes:
        before = changes[str(serena)]['before']
        if before not in {'908581c1c1f84fe721cd606578158a17e50f1824a93ef177b7bfae14fd8dccc4',
                          '0635b3ac111b4f9ecd446768f6157ba43cb7c08bce45c048bbcd64311ae1dcc2'}:
            raise ValueError('Serena migration requires explicit review of the predecessor implementation')
        plan.setdefault('compatible_worker_hashes', {}).setdefault(serena.name, []).append(before)
        plan['resume_revision']['adapter_changes'] = {'serena_failure_recovery': {
            'before': plan['policy'].get('serena_failure_recovery', 'stop on match-overflow'),
            'after': 'relative/root exact-match on overflow; max 8 total calls'}}
        plan['policy']['serena_failure_recovery'] = 'relative/root exact-match on overflow; max 8 total calls'
    if str(serena) in changes or str(coco) in changes:
        plan['worker_compatibility_scope'] = ('Reuse verified successful predecessor results only; '
            'Serena normal query path unchanged, recovery applies only to previously failing match-overflow calls. '
            'CocoIndex adds a transport-capability preflight; successful indexing/query behavior unchanged. '
            'Failed engines are retried, never reclassified in place.')
    output.mkdir(parents=True, exist_ok=False)
    path = output/'plan.json'
    path.write_text(json.dumps(plan, indent=2), encoding='utf-8')
    path.with_suffix('.sha256').write_text(digest(path)+'\n', encoding='utf-8')
    return path


def reuse_baseline(project, task, directory, policy):
    if digest(directory/'instance.jsonl') != task['dataset_sha256']:
        raise ValueError('Prior baseline dataset differs from frozen input')
    repo = project/'.keel/swe-snapshots'/task['repository'].replace('/', '--')/task['base_commit']
    instance = load_swe_instance(directory/'instance.jsonl', task['instance_id'], repo)
    sweep = directory/'sweep-code-aware'
    rows = [json.loads(s) for s in (sweep/'runs.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
    passed = [r for r in rows if r['status'] == 'passed' and r['mode'] == 't1' and r['line_budget'] == 100]
    if len(passed) != 1:
        raise ValueError('Expected one completed prior T1 result')
    saved = passed[0]['result']
    with RepositoryIndex(repo) as index:
        index.require_fresh()
        if not index_coverage(index, policy.get('index_coverage', 'strict'))['eligible']:
            raise ValueError('Prior baseline is not eligible under the requested corpus policy')
        if (saved['instance_id'] != task['instance_id'] or saved['base_commit'] != task['base_commit'] or
                saved['index_ref'] != index.metadata['index_ref'] or
                index.metadata['embedding']['model'] != policy['compass_embedding'] or
                saved['context_packing']['symbol_line_cap'] != 32):
            raise ValueError('Prior baseline source/config identity mismatch')
    candidates = [{**r, 'start_line': r['start'], 'end_line': r['end']} for r in saved['candidates']]
    if score(candidates, instance)['metrics'] != saved['metrics']:
        raise ValueError('Prior baseline metrics do not reproduce')
    return {'instance_id': task['instance_id'], 'snapshot': str(repo),
        'measurements': [{'ranking': 'code-aware', 'sweep': str(sweep/'sweep.json')}]}


def completed_baseline(directory):
    path = directory/'sweep-code-aware/runs.jsonl'
    if not path.is_file():
        return False
    rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
    return any(r['status'] == 'passed' and r['mode'] == 't1' and r['line_budget'] == 100 for r in rows)


def bounded_index(repo, directory, model, timeout):
    progress = directory/'index-progress.json'
    with (directory/'index.log').open('wb') as log:
        command = [sys.executable, str(Path(__file__).with_name('build_validation_index.py')),
                   '--repo', str(repo), '--progress', str(progress), '--model', model, '--timeout', str(timeout)]
        with subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT) as process:
            started = time.monotonic()
            while process.poll() is None:
                remaining = timeout+15-(time.monotonic()-started)
                if remaining <= 0:
                    process.kill()
                    process.wait()
                    raise TimeoutError('Index subprocess time limit reached; checkpoints retained')
                try:
                    process.wait(timeout=min(10, remaining))
                except subprocess.TimeoutExpired:
                    current = json.loads(progress.read_text()) if progress.exists() else {}
                    print('[Index] '+repo.parent.name+' '+current.get('stage', 'starting')+
                        f" vectors={current.get('vectors_completed', '?')}/{current.get('symbols_total', '?')}"+
                        f" files={current.get('files_completed', '?')}"+
                        f" elapsed={int(time.monotonic()-started)}s", flush=True)
            if process.returncode:
                current = json.loads(progress.read_text()) if progress.exists() else {}
                raise ValueError(current.get('error', 'Index worker failed; inspect index.log'))


def inspect_resume(project, plan_path, previous, output, *, coverage_policy=None):
    if output.exists():
        raise FileExistsError('Resume-check output must be new')
    revised = resume_plan(project, plan_path, previous, output/'resume-plan', coverage_policy=coverage_policy)
    plan = verify_plan(revised)
    prior = json.loads((previous/'validation.json').read_text(encoding='utf-8'))
    old_rows = {r['instance_id']: r for r in prior['records']}
    records = []
    for number, task in enumerate(plan['tasks'], 1):
        old = old_rows.get(task['instance_id'], {})
        directory = Path(old.get('reuse_source', previous/f'instance-{number:03d}'))
        if old.get('status') == 'baseline_ready' or completed_baseline(directory):
            reuse_baseline(project, task, directory, plan['policy'])
            action = 'reuse_completed_baseline'
        elif old.get('error') == 'Invalid SWE line interval':
            action = 'retain_input_failure'
        else:
            action = 'continue_unfinished_baseline'
        records.append({'instance_id': task['instance_id'], 'action': action})
    result = {'status': 'resume_checked', 'records': records, 'effective_plan': str(revised),
              'new_model_calls': 0, 'scope': 'Read-only result verification; no indexing/retrieval/inference'}
    (output/'resume-check.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def execute(project, plan_path, output, *, resume_from=None, index_timeout=1800, coverage_policy=None):
    if resume_from:
        if output.exists():
            raise FileExistsError('Resume output must be a new directory; previous run is retained')
        plan_path = resume_plan(project, plan_path, resume_from, output/'resume-plan', coverage_policy=coverage_policy)
    elif coverage_policy is not None:
        raise ValueError('Coverage amendment requires an explicit resume with a derived plan')
    plan = verify_plan(plan_path)
    output.mkdir(parents=True, exist_ok=bool(resume_from))
    report = {'status': 'running', 'plan_sha256': digest(plan_path), 'records': [], 'benchmark_ready': False}
    def save():
        atomic_json(output/'validation.json', report)
    save()
    source = {'instances': []}
    policy = plan['policy']
    report['index_coverage_policy'] = policy.get('index_coverage', 'strict')
    previous = json.loads((resume_from/'validation.json').read_text()) if resume_from else {'records': []}
    previous_rows = {r['instance_id']: r for r in previous['records']}
    report['resume_from'] = str(resume_from) if resume_from else None
    report['effective_plan'] = str(plan_path)
    for number, task in enumerate(plan['tasks'], 1):
        row = {'instance_id': task['instance_id'], 'repository': task['repository'], 'stage': 'snapshot', 'status': 'running'}
        report['records'].append(row)
        save()
        print('[Validation] '+task['instance_id']+' snapshot', flush=True)
        try:
            old = previous_rows.get(task['instance_id'], {})
            prior_directory = Path(old.get('reuse_source', resume_from/f'instance-{number:03d}')) if resume_from else None
            if old.get('status') == 'baseline_ready' or (prior_directory and completed_baseline(prior_directory)):
                completed = reuse_baseline(project, task, prior_directory, policy)
                source['instances'].append(completed)
                row.update(status='baseline_ready', stage='baseline_ready', reused=True,
                    reuse_source=str(prior_directory),
                    reuse_runs_sha256=digest(prior_directory/'sweep-code-aware/runs.jsonl'))
                print('[Validation] '+task['instance_id']+' reuse verified completed baseline', flush=True)
                save()
                continue
            if old.get('error') == 'Invalid SWE line interval':
                # Deterministic input failure remains an exclusion; do not edit
                # reference labels or repeat an unchanged failing validation.
                row.update(status='input_failed', stage='input_validation', reused_failure=True, error=old['error'])
                save()
                continue
            repo = prepare_snapshot(task['repository'], task['base_commit'],
                project/'.keel/swe-snapshots'/task['repository'].replace('/', '--')/task['base_commit'], timeout=60)
            directory = output/f'instance-{number:03d}'
            directory.mkdir()
            dataset = directory/'instance.jsonl'
            dataset.write_bytes(Path(task['dataset']).read_bytes())
            instance = load_swe_instance(dataset, task['instance_id'], repo)
            row['stage'] = 'compass_index'
            save()
            print('[Validation] '+task['instance_id']+' Compass index', flush=True)
            bounded_index(repo, directory, policy['compass_embedding'], index_timeout)
            row['stage'] = 'compass_t1'
            save()
            with RepositoryIndex(repo) as index:
                coverage = index_coverage(index, policy.get('index_coverage', 'strict'))
                row['index_coverage'] = coverage
                save()
                sweep = directory/'sweep-code-aware'
                result = run_swe_sweep(index, instance, sweep, modes=('t1',), line_budgets=(100,), repeats=1,
                    seed=plan['seed'], routing=Routing(ranking='code-aware', evidence_policy='read'),
                    limits=Limits(max_wallclock=300, max_tool_calls=100, max_tokens=30000, max_model_calls=4),
                    repository_id=task['repository'], symbol_line_cap=32,
                    coverage_policy=policy.get('index_coverage', 'strict'))
                if not result['all_passed']:
                    raise ValueError('Compass T1 failed; inspect retained sweep')
                row['embedding_spec'] = index.metadata['embedding']
            source['instances'].append({'instance_id': task['instance_id'], 'snapshot': str(repo),
                'measurements': [{'ranking': 'code-aware', 'sweep': str(sweep/'sweep.json')} ]})
            row.update(status='baseline_ready', stage='baseline_ready')
        except Exception as error:
            row.update(status='infrastructure_failed', error_type=type(error).__name__, error=str(error)[:1500])
        save()
    # Retain failures; no reserve promotion and no averaging missing tasks as zero.
    (output/'source-result.json').write_text(json.dumps(source, indent=2), encoding='utf-8')
    if source['instances']:
        try:
            report['active_stage'] = 'external_retrieval'
            save()
            compare(output/'source-result.json', output/'external',
                project/'.keel/tools/serena-venv/Scripts/python.exe', policy['pyright_command'],
                cocoindex_python=project/'.keel/tools/cocoindex-venv/Scripts/python.exe',
                engines=('serena_symbols', 'cocoindex_semantic'),
                resume_report=(resume_from/'external/comparison.json') if resume_from and
                    (resume_from/'external/comparison.json').is_file() else None,
                compatible_worker_hashes=plan.get('compatible_worker_hashes'))
            report['active_stage'] = 'reranking'
            save()
            evaluation = evaluate(output/'source-result.json', [output/'external/comparison.json'], output/'reranking',
                project/'.keel/tools/cocoindex-venv/Scripts/python.exe', revision=policy['reranker_revision'],
                model_cache=Path(policy['reranker_model_cache']), local_files_only=True,
                resume_from=(resume_from/'reranking') if resume_from and
                    (resume_from/'reranking/worker-result.json').is_file() else None)
            if evaluation['status'] != 'completed':
                raise ValueError('Reranking failed; inspect reranking/evaluation.json')
            report['active_stage'] = 'fusion'
            save()
            fusion = replay(output/'source-result.json', [output/'external/comparison.json'],
                output/'reranking/evaluation.json', output/'fusion')
            report['summary'] = fusion['summary']
            report['excluded_engines'] = fusion['source_exclusions']
            report['status'] = 'completed' if all(r['status'] == 'baseline_ready' for r in report['records']) and \
                not fusion['source_exclusions'] else 'incomplete'
        except Exception as error:
            report.update(status='incomplete', pipeline_error=str(error)[:1500])
    else:
        report['status'] = 'no_runnable_tasks'
    report['planned_tasks'] = len(plan['tasks'])
    report['baseline_ready_tasks'] = len(source['instances'])
    report['active_stage'] = 'finished'
    save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume-from', type=Path)
    parser.add_argument('--index-timeout', type=int, default=1800)
    parser.add_argument('--check-resume', action='store_true')
    parser.add_argument('--index-coverage', choices=POLICIES,
                        help='Explicit derived-plan corpus amendment on resume; strict remains the default')
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    if args.index_coverage and not args.resume_from:
        parser.error('--index-coverage requires --resume-from')
    if args.check_resume:
        if not args.plan or not args.resume_from or args.execute:
            parser.error('--check-resume requires --plan and --resume-from, without --execute')
        result = inspect_resume(project, args.plan.resolve(), args.resume_from.resolve(), args.output.resolve(),
                                coverage_policy=args.index_coverage)
    elif args.execute:
        if not args.plan:
            parser.error('--execute requires an already frozen --plan')
        if args.index_timeout < 30:
            parser.error('--index-timeout must be at least 30 seconds')
        result = execute(project, args.plan.resolve(), args.output.resolve(),
            resume_from=args.resume_from.resolve() if args.resume_from else None, index_timeout=args.index_timeout,
            coverage_policy=args.index_coverage)
    else:
        if args.plan:
            parser.error('--plan is used with --execute; omit both to freeze a new sample')
        result = freeze(project, args.output.resolve())
    print(json.dumps(result, indent=2))
