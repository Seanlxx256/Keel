"""Install pinned native Aider in isolation, probe it, and run an issue-only comparison."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json, ProgressLog


def setup(output, environment, source, *, skip_install=False, timeout=1800, resume_report=None):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = environment.resolve()
    interpreter = environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    deadline = time.monotonic()+timeout
    report = dict(status='running', commands=[], generation_model_calls=0,
        package='aider-chat==0.86.2', environment=str(environment), scope='Native ranking component, not full Aider',
        pip_no_index=os.environ.get('PIP_NO_INDEX'), resume_report=str(resume_report) if resume_report else None)
    if source:
        raw = source.resolve(strict=True).read_bytes()
        report['source_sha256'] = hashlib.sha256(raw).hexdigest()
        report['task_ids'] = [r['instance_id'] for r in json.loads(raw)['instances']]
    report['policy'] = dict(engine='aider_native_tags', line_budget=100,
        symbol_line_cap=32, candidate_cap=100, hash_seed=0, chat_files=[], generation_model_calls=0)
    report['adapter_sha256'] = hashlib.sha256(
        Path(__file__).with_name('aider_retrieval_worker.py').read_bytes()).hexdigest()
    def save():
        atomic_json(output/'setup.json', report)
    def command(stage, argv):
        report['stage'] = stage
        save()
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Setup budget exhausted')
        with (output/(stage+'.log')).open('wb') as log, \
                ProgressLog(output/(stage+'-progress.jsonl'), console=True, interval=10) as progress:
            progress.emit(stage, log=str(output/(stage+'.log')))
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                env=dict(os.environ, PYTHONHASHSEED='0', PYTHONUTF8='1'))
            try:
                code = child.wait(timeout=remaining)
            except BaseException:
                child.kill()
                child.wait()
                raise
        report['commands'].append(dict(stage=stage, returncode=code))
        save()
        if code:
            raise RuntimeError(stage+' failed; inspect '+str(output/(stage+'.log')))
    save()
    try:
        if not interpreter.is_file():
            if skip_install:
                raise FileNotFoundError('Isolated Aider environment unavailable')
            command('environment', [sys.executable, '-m', 'venv', str(environment)])
        if not skip_install:
            command('install', [str(interpreter), '-m', 'pip', 'install', '--disable-pip-version-check',
                '--retries', '0', '--timeout', '20', report['package']])
        command('versions', [str(interpreter), '-m', 'pip', 'freeze'])
        command('probe', [str(interpreter), '-c',
            'from aider.repomap import RepoMap; from importlib.metadata import version; '
            'assert version("aider-chat")=="0.86.2"; print(version("aider-chat")); '
            'assert callable(RepoMap.get_ranked_tags)'])
        report['status'] = 'ready'
        if source:
            if hashlib.sha256(source.read_bytes()).hexdigest() != report['source_sha256']:
                raise ValueError('Frozen source report changed during setup')
            command('comparison', [sys.executable, str(Path(__file__).with_name('compare_retrieval_alternatives.py')),
                '--source', str(source.resolve(strict=True)), '--output', str(output/'comparison'),
                '--aider-python', str(interpreter), '--engines', 'aider_native_tags',
                '--engine-timeout', str(max(30, min(600, int(deadline-time.monotonic()))))]+
                (['--resume-report', str(resume_report.resolve(strict=True))] if resume_report else []))
            measured = json.loads((output/'comparison/comparison.json').read_text(encoding='utf-8'))
            rows = [r for r in measured['records'] if r['engine'] == 'aider_native_tags']
            report.update(status='evaluated' if rows and all(r['status']=='ok' for r in rows) else 'evaluation_incomplete',
                evaluated_tasks=sum(r['status']=='ok' for r in rows), planned_tasks=len(rows),
                comparison=str(output/'comparison/comparison.json'))
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error)[:1000])
    save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--environment', type=Path, default=Path('.keel/tools/aider-retrieval-venv'))
    parser.add_argument('--source', type=Path)
    parser.add_argument('--skip-install', action='store_true')
    parser.add_argument('--resume-report', type=Path)
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    result = setup(args.output, args.environment, args.source, skip_install=args.skip_install,
                   timeout=args.timeout, resume_report=args.resume_report)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] in ('ready', 'evaluated') else 1)
