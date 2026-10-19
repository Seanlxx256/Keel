"""Run installed CocoIndex Code on a disposable tracked-file copy, without labels."""
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.ipc import probe_named_pipe


def copy_snapshot(repo, destination, omissions=None):
    repo = repo.resolve(strict=True)
    if destination.resolve().is_relative_to(repo):
        raise ValueError('Disposable copy must be outside the source snapshot')
    listing = subprocess.run(['git', '-c', 'safe.directory='+str(repo), 'ls-files', '--stage', '-z'],
                             cwd=repo, capture_output=True, check=True, timeout=30).stdout
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {}
    for raw in listing.split(b'\0'):
        if not raw:
            continue
        attributes, relative_bytes = raw.split(b'\t', 1)
        mode, oid, stage = attributes.decode('ascii').split()
        if stage != '0':
            raise ValueError('Unmerged tracked entry')
        relative = relative_bytes.decode('utf-8')
        source = repo/relative
        if mode == '120000':
            # Do not dereference links or index Windows symlink placeholders
            # as if their target-path text were source code.
            if omissions is not None:
                omissions.append({'path': relative, 'blob': oid, 'reason': 'git_symlink_not_indexed'})
            continue
        if mode == '160000':
            if source.is_symlink() or not source.resolve().is_relative_to(repo):
                raise ValueError('Submodule path escapes snapshot: '+relative)
            if source.exists() and (not source.is_dir() or any(source.iterdir())):
                raise ValueError('Initialized submodule requires an explicit corpus policy: '+relative)
            if omissions is not None:
                omissions.append({'path': relative, 'commit': oid, 'reason': 'uninitialized_git_submodule'})
            continue
        if mode not in ('100644', '100755'):
            raise ValueError('Unsupported tracked mode: '+mode+' '+relative)
        if source.is_symlink() or not source.resolve().is_relative_to(repo) or not source.is_file():
            raise ValueError('Unsupported tracked path: '+relative)
        target = destination/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        manifest[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
    return manifest


def parse_search(payload, repo):
    if not isinstance(payload, dict) or payload.get('success') is not True:
        raise ValueError('CocoIndex search did not report success')
    if not isinstance(payload.get('results'), list):
        raise ValueError('CocoIndex search schema missing results list')
    result = []
    for row in payload['results'][:100]:
        path, start, end = row.get('file_path'), row.get('start_line'), row.get('end_line')
        if not isinstance(path, str) or type(start) is not int or type(end) is not int:
            raise ValueError('CocoIndex search returned an invalid range schema')
        target = (repo/path).resolve(strict=True)
        if (not target.is_relative_to(repo) or not target.is_file() or
                not 1 <= start <= end <= len(target.read_bytes().splitlines())):
            raise ValueError('CocoIndex search returned an invalid source range')
        result.append({'path': target.relative_to(repo).as_posix(),
                       'start_line': start, 'end_line': end})
    return result


def restore_checkpoint(previous, root, manifest, version, embedding):
    """Clone a stopped native checkpoint; never mutate the preceding run."""
    previous = Path(previous).resolve(strict=True)
    report = json.loads((previous/'result.json').read_text(encoding='utf-8'))
    if report.get('daemon_cleanup_returncode') != 0:
        raise ValueError('Checkpoint daemon was not confirmed stopped')
    if report.get('version') != version or report.get('embedding_settings') != embedding:
        raise ValueError('Checkpoint package/model settings differ')
    archived = json.loads((previous/'source-manifest.json').read_text(encoding='utf-8'))
    if archived != manifest:
        raise ValueError('Checkpoint source manifest differs')
    source = previous/'snapshot'
    for relative, digest in manifest.items():
        path = source/relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Checkpoint source bytes differ: '+relative)
    native = source/'.cocoindex_code'
    if json.loads((native/'settings.yml').read_text()) != {'include_patterns': ['**/*.py']}:
        raise ValueError('Checkpoint corpus settings differ')
    if any(p.is_symlink() for p in native.rglob('*')):
        raise ValueError('Checkpoint contains symlinks')
    shutil.copytree(native, root/'.cocoindex_code')
    return {'source': str(previous), 'status': 'cloned',
            'scope': 'Native incremental index revalidation; embedding reuse is not independently measured'}


def native_index_command(root):
    # The upstream client translates host mappings but does NOT resolve relative
    # paths. Use the same canonical project identity as CLI search.
    return [sys.executable, '-u', '-c',
        'import json,sys,msgspec; from cocoindex_code import client; '
        'emit=lambda p: print(json.dumps(msgspec.to_builtins(p)),flush=True); '
        'r=client.index(sys.argv[1],on_progress=emit,on_waiting=lambda: print("waiting",flush=True)); '
        'emit(r); raise SystemExit(0 if r.success else 1)', str(root.resolve(strict=True))]


def retrieve(config, output):
    directory = output.parent.resolve()
    report = {'status': 'running', 'stage': 'package_probe', 'commands': [],
              'generation_model_calls': 0, 'embedding_usage': 'not measured',
              'adapter': 'Full issue query; native Python AST chunks and local embeddings; no reranker.'}
    def save():
        output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    started = time.monotonic()
    timeout = config.get('timeout', 900)
    state = directory/'cocoindex-state'
    env = dict(os.environ, COCOINDEX_CODE_DIR=str(state), PYTHONUTF8='1')
    # Remove inherited routing overrides so the copy/state remain isolated.
    for name in ('COCOINDEX_CODE_HOST_CWD', 'COCOINDEX_CODE_DB_PATH_MAPPING',
                 'COCOINDEX_CODE_HOST_PATH_MAPPING'):
        env.pop(name, None)
    env['HF_HOME'] = str(Path(config['model_cache']).resolve())
    root = directory/'snapshot'
    cli = [sys.executable, '-c', 'from cocoindex_code.cli import app; app()']
    def command(stage, args, *, seconds=None):
        report['stage'] = stage
        save()
        remaining = timeout-(time.monotonic()-started)
        if remaining <= 0:
            raise TimeoutError('CocoIndex worker wall-clock limit reached')
        invocation = cli+args
        if stage == 'index':
            # The native CLI uses a transient Rich spinner, invisible in redirected logs.
            invocation = native_index_command(root)
        with (directory/(stage+'.stdout.log')).open('wb') as stdout, \
                (directory/(stage+'.stderr.log')).open('wb') as stderr:
            process = subprocess.Popen(invocation, cwd=root, env=env, stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr)
            deadline = time.monotonic()+min(seconds or remaining, remaining)
            try:
                while True:
                    try:
                        process.wait(timeout=min(10, max(.01, deadline-time.monotonic())))
                        break
                    except subprocess.TimeoutExpired:
                        report['elapsed_seconds'] = time.monotonic()-started
                        report['progress_log'] = str(directory/(stage+'.stdout.log'))
                        save()
                        print('[CocoIndex] '+stage+' elapsed='+str(round(report['elapsed_seconds']))+
                              's log_bytes='+str((directory/(stage+'.stdout.log')).stat().st_size), flush=True)
                        if time.monotonic() >= deadline:
                            raise
            except BaseException:
                process.kill()
                process.wait()
                report['commands'].append({'stage': stage, 'arguments': args,
                    'returncode': process.returncode, 'interrupted': True})
                raise
        report['commands'].append({'stage': stage, 'arguments': args, 'returncode': process.returncode})
        save()
        if process.returncode:
            detail = (directory/(stage+'.stderr.log')).read_text(encoding='utf-8', errors='replace').strip()
            if not detail:
                detail = (directory/(stage+'.stdout.log')).read_text(encoding='utf-8', errors='replace').strip()
            raise RuntimeError(stage+' failed: '+detail[-1500:])
        return (directory/(stage+'.stdout.log')).read_text(encoding='utf-8')
    try:
        report['version'] = metadata.version('cocoindex-code')
        report['stage'] = 'ipc_preflight'
        save()
        report['ipc_preflight'] = probe_named_pipe(sys.executable)
        if report['ipc_preflight']['status'] == 'unavailable':
            report.update(status='unavailable', error_type='TransportUnavailable',
                error='Selected interpreter cannot complete local Windows named-pipe IPC; inspect ipc_preflight. '
                      'No source copy, model load or daemon startup attempted.')
            return report
        report['stage'] = 'snapshot_copy'
        save()
        omissions = []
        manifest = copy_snapshot(Path(config['repo']), root, omissions)
        report['omitted_entries'] = omissions
        report['omitted_gitlinks'] = [r for r in omissions if r['reason'] == 'uninitialized_git_submodule']
        (directory/'source-manifest.json').write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
        report['source_manifest_sha256'] = hashlib.sha256(
            (directory/'source-manifest.json').read_bytes()).hexdigest()
        state.mkdir(parents=True, exist_ok=False)
        # JSON is valid YAML. Only supported public configuration fields are used.
        # Omit prompt kwargs so installed upstream model defaults remain effective.
        model = config.get('embedding_model', 'Snowflake/snowflake-arctic-embed-xs')
        settings = {'embedding': {'provider': 'sentence-transformers', 'model': model},
                    'daemon': {'idle_timeout_minutes': 2, 'keep_alive_with_mcp': False}}
        (state/'global_settings.yml').write_text(json.dumps(settings), encoding='utf-8')
        report['embedding_settings'] = settings['embedding']
        report['model_revision'] = 'upstream default; not independently pinned'
        if config.get('resume_checkpoint'):
            report['checkpoint'] = restore_checkpoint(config['resume_checkpoint'], root,
                manifest, report['version'], settings['embedding'])
        else:
            command('init', ['init', '--force'])
        project = root/'.cocoindex_code/settings.yml'
        # Same Python language scope as the historical Compass corpus; native
        # CocoIndex chunking remains independent of Compass symbol boundaries.
        project.write_text(json.dumps({'include_patterns': ['**/*.py']}), encoding='utf-8')
        command('index', ['index'])
        raw = command('search', ['search', '--json', '--lang', 'python', '--limit', '100', '--', config['query']])
        payload = json.loads(raw)
        (directory/'raw-search.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
        candidates = parse_search(payload, root)
        for relative, digest in manifest.items():
            if hashlib.sha256((root/relative).read_bytes()).hexdigest() != digest:
                raise ValueError('Tracked source bytes changed in disposable copy: '+relative)
        report.update(status='ok', stage='finished', candidates=candidates,
                      source_copy_unchanged=True)
    except metadata.PackageNotFoundError as error:
        report.update(status='unavailable', error_type=type(error).__name__,
                      error='cocoindex-code is not installed in the selected interpreter')
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error)[:1000])
    finally:
        # Only the daemon using this newly created state directory is addressed.
        if state.is_dir() and root.is_dir():
            try:
                with (directory/'daemon-cleanup.log').open('wb') as log:
                    stopped = subprocess.run(cli+['daemon', 'stop'], cwd=root, env=env,
                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=15)
                    report['daemon_cleanup_returncode'] = stopped.returncode
            except Exception as error:
                report['daemon_cleanup_error'] = type(error).__name__
        report['seconds_including_indexing'] = time.monotonic()-started
        save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    retrieve(json.loads(args.input.read_text(encoding='utf-8')), args.output.resolve())
