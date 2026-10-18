"""Install CocoIndex in its own venv and optionally run the frozen retrieval comparison."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def setup(output, environment, source=None, *, skip_install=False, timeout=1800):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = environment.resolve()
    python = environment/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    report = {'status': 'running', 'stage': 'environment', 'model_calls': 0,
              'environment': str(environment), 'commands': []}
    started = time.monotonic()
    def save():
        (output/'setup.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    def execute(stage, arguments):
        report['stage'] = stage
        save()
        print('[CocoIndex] '+stage+'; log: '+str(output/(stage+'.log')), flush=True)
        remaining = timeout-(time.monotonic()-started)
        if remaining <= 0:
            raise TimeoutError('Setup wall-clock limit reached')
        with (output/(stage+'.log')).open('wb') as log:
            with subprocess.Popen(arguments, stdout=log, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL) as result:
                deadline = time.monotonic()+remaining
                while result.poll() is None:
                    wait = deadline-time.monotonic()
                    if wait <= 0:
                        result.kill()
                        result.wait()
                        raise TimeoutError(stage+' wall-clock limit reached')
                    try:
                        result.wait(timeout=min(10, wait))
                    except subprocess.TimeoutExpired:
                        size = (output/(stage+'.log')).stat().st_size
                        print(f'[CocoIndex] {stage} running; log bytes={size}', flush=True)
        report['commands'].append({'stage': stage, 'returncode': result.returncode})
        save()
        if result.returncode:
            raise RuntimeError(stage+' failed; inspect '+stage+'.log')
    save()
    try:
        if not python.is_file():
            if skip_install:
                raise FileNotFoundError('Isolated CocoIndex interpreter does not exist')
            execute('create-venv', [sys.executable, '-m', 'venv', str(environment)])
        if not skip_install:
            execute('install', [str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                '--retries', '1', '--timeout', '30', 'cocoindex-code[embeddings-local]',
                'sentence-transformers>=3.3.1'])
        execute('versions', [str(python), '-m', 'pip', 'freeze'])
        execute('probe', [str(python), '-m', 'cocoindex_code.cli', 'version'])
        # A CLI version does not exercise optional local embedding dependencies.
        # Import them before launching three independent indexing attempts.
        execute('embedding-import', [str(python), '-c',
            'import sentence_transformers, torch; '
            'from importlib.metadata import version; '
            'print("sentence-transformers="+version("sentence-transformers")); '
            'print("torch="+version("torch"))'])
        report.update(status='ready', stage='finished', python=str(python))
        if source:
            execute('comparison', [sys.executable, str(Path(__file__).with_name('compare_retrieval_alternatives.py')),
                '--source', str(source.resolve(strict=True)), '--output', str(output/'comparison'),
                '--cocoindex-python', str(python), '--engines', 'cocoindex_semantic'])
            measured = json.loads((output/'comparison/comparison.json').read_text(encoding='utf-8'))
            rows = [r for r in measured['records'] if r['engine'] == 'cocoindex_semantic']
            report.update(status='evaluated' if rows and all(r['status'] == 'ok' for r in rows)
                          else 'evaluation_incomplete', stage='finished',
                          evaluated_tasks=sum(r['status'] == 'ok' for r in rows),
                          planned_tasks=len(rows), comparison=str(output/'comparison/comparison.json'))
            report['failures'] = [{key: r.get(key) for key in ('instance', 'stage', 'detail', 'worker_result')}
                                  for r in rows if r['status'] != 'ok']
    except Exception as error:
        report.update(status='setup_failed' if report['stage'] != 'comparison' else 'evaluation_failed',
                      error_type=type(error).__name__, error=str(error)[:1000])
    report['seconds'] = time.monotonic()-started
    save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--environment', type=Path, default=Path('.keel/tools/cocoindex-venv'))
    parser.add_argument('--source', type=Path)
    parser.add_argument('--skip-install', action='store_true')
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    result = setup(args.output, args.environment, args.source, skip_install=args.skip_install, timeout=args.timeout)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['status'] in ('ready', 'evaluated') else 1)
