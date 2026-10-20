"""Probe host and local Docker-image connectivity without changing network settings."""
import argparse
import json
from pathlib import Path
import sys
import hashlib
import re
import shlex
import subprocess
import uuid
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.network_probe import diagnose, diagnostic_excerpt, bounded_apt_attempts
from examples.swebench_bridge import run_harness


def extract_apt(script):
    lines = [line.strip() for line in script.splitlines() if line.strip().startswith('apt-get ')]
    if len(lines) != 1:
        raise ValueError('Require exactly one standalone APT command chain; manual review needed')
    command = lines[0]
    operations = []
    for segment in command.split('&&'):
        tokens = shlex.split(segment)
        if tokens[:1] == ['DEBIAN_FRONTEND=noninteractive']:
            tokens.pop(0)
        if not tokens or tokens.pop(0) != 'apt-get':
            raise ValueError('Only apt-get commands are accepted')
        if any(not re.fullmatch(r'[A-Za-z0-9.+:=_-]+', token) for token in tokens):
            raise ValueError('Unsupported APT token')
        verbs = [token for token in tokens if token in ('update', 'upgrade', 'install')]
        if len(verbs) != 1:
            raise ValueError('Only update/upgrade/install are supported')
        operations.extend(verbs)
    if operations != ['update', 'upgrade', 'install']:
        raise ValueError('Require update, upgrade, install in original order')
    return command


def apt_workload(script_path, image, output, timeout, *, attempts=1, transport='original'):
    if not 60 <= timeout <= 7200:
        raise ValueError('APT workload deadline must be 60..7200 seconds')
    if not 1 <= attempts <= 3:
        raise ValueError('APT attempts must be 1..3')
    if transport not in ('original', 'no_pipeline'):
        raise ValueError('Unsupported transport policy')
    deadline = time.monotonic()+timeout
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]*', image) or image.startswith('sha256:'):
        raise ValueError('Use a named local image')
    source = script_path.read_bytes()
    command = extract_apt(source.decode('utf-8'))
    result = {'status': 'running', 'source_sha256': hashlib.sha256(source).hexdigest(),
              'apt_command': command, 'image': image, 'timeout_seconds': timeout, 'max_attempts': attempts, 'transport': transport,
              'scope': 'Separate diagnostic build; archives retained by disabling docker-clean in this image only. No source or package-list change; not a reference score.'}
    def save():
        (output/'diagnosis.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    save()
    tag = 'keel-apt-workload:'+uuid.uuid4().hex
    try:
        inspected = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
            capture_output=True, text=True, timeout=10, check=True)
        identity = inspected.stdout.strip()
        result['base_image_id'] = identity
        key = hashlib.sha256(identity.encode()).hexdigest()[:24]
        context = output/'build-context'
        context.mkdir()
        prefix = ''
        if transport == 'no_pipeline':
            prefix = "printf '%s\\n' 'Acquire::http::Pipeline-Depth \"0\";' > /tmp/keel-apt-transport.conf\nexport APT_CONFIG=/tmp/keel-apt-transport.conf\n"
        (context/'apt.sh').write_bytes(('#!/bin/bash\nset -euxo pipefail\n'+prefix+command+'\n').encode('utf-8'))
        (context/'Dockerfile').write_text('FROM '+image+'\nCOPY apt.sh /keel-apt.sh\n'
            'RUN rm -f /etc/apt/apt.conf.d/docker-clean\n'
            'RUN --mount=type=cache,id=keel-apt-'+key+',target=/var/cache/apt/archives,sharing=locked '
            '/bin/bash /keel-apt.sh\n', encoding='utf-8', newline='\n')
        def execute(log, remaining):
            return run_harness(['docker', 'build', '--pull=false', '--no-cache', '--progress=plain',
                '-t', tag, str(context.resolve())], cwd=output.resolve(), log_path=log, timeout=remaining)
        def save_attempts(rows):
            result['attempts'] = list(rows)
            save()
        rows = bounded_apt_attempts(execute, output, attempts=attempts, deadline=deadline, save=save_attempts)
        after = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
            capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        result.update(returncode=rows[-1]['returncode'] if rows else None,
                      status='apt_completed' if rows and rows[-1]['passed'] else 'apt_failed')
        if after != identity:
            result['status'] = 'base_identity_changed'
    except BaseException as error:
        result.update(status='diagnostic_error', error_type=type(error).__name__)
        if isinstance(error, subprocess.CalledProcessError):
            result['diagnostic'] = diagnostic_excerpt(error.stderr or '')
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        save()
        try:
            subprocess.run(['docker', 'image', 'rm', tag], capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    parser.add_argument('--inspect-grade', type=Path, help='Read-only runtime inspection of the archived instance image')
    parser.add_argument('--check-scm-plugins', action='store_true', help='Compare registered SCM version-scheme providers without modifying packages')
    parser.add_argument('--apt-script', type=Path, help='Diagnose the original update/upgrade/install chain in a separate cached build')
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--attempts', type=int, default=1, help='APT workload attempts, 1..3, sharing the total deadline')
    parser.add_argument('--failed-workload', type=Path, help='Previous workload evidence for bounded model diagnosis')
    parser.add_argument('--model-config', type=Path)
    parser.add_argument('--image', help='Existing local image; never pulled')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--download', action='store_true', help='Read to EOF within byte cap')
    parser.add_argument('--build', action='store_true', help='Probe a disposable build using the local image')
    parser.add_argument('--apt-build', action='store_true', help='Download the URL using APT acquisition in a disposable build; no install/update')
    parser.add_argument('--max-bytes', type=int, default=8388608)
    args = parser.parse_args()
    if sum(bool(v) for v in (args.url,args.apt_script,args.inspect_grade)) != 1:
        parser.error('Provide exactly one of --url, --apt-script or --inspect-grade')
    if args.check_scm_plugins and not args.inspect_grade:
        parser.error('--check-scm-plugins requires --inspect-grade')
    if not args.inspect_grade and not args.image:
        parser.error('Network modes require --image')
    if args.apt_script and (args.download or args.build or args.apt_build):
        parser.error('APT workload mode cannot combine URL probe flags')
    if (args.failed_workload or args.model_config) and not (args.apt_script and args.failed_workload and args.model_config):
        parser.error('Network ReAct requires --apt-script, --failed-workload and --model-config together')
    args.output.mkdir(parents=True, exist_ok=False)
    if args.inspect_grade:
        from keel.environment_probe import inspect_image
        result = inspect_image(args.inspect_grade.resolve(),
            ['setuptools_scm','vcs_versioning','pytest'],['setuptools-scm','vcs-versioning','pytest','setuptools'],timeout=45,
            plugin_probe=args.check_scm_plugins)
        if result.get('returncode')==0:
            try:
                result['observation']=json.loads(result['stdout'])
            except ValueError:
                result['error']='Inspection returned invalid JSON'
        (args.output/'inspection.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))
        return
    if args.apt_script:
        if args.failed_workload:
            if not args.model_config:
                parser.error('Model diagnosis requires --model-config')
            from keel.models import from_config
            from keel.network_recovery import recover_network
            result = recover_network(args.failed_workload, args.apt_script, args.image, args.output,
                from_config(json.loads(args.model_config.read_text(encoding='utf-8'))), apt_workload,
                timeout=args.timeout)
            print(json.dumps(result, indent=2))
            return
        result = apt_workload(args.apt_script, args.image, args.output, args.timeout, attempts=args.attempts)
        print(json.dumps(result, indent=2))
        return
    result = diagnose(args.url, args.image, download=args.download, build=args.build, max_bytes=args.max_bytes, apt_build=args.apt_build,
        progress=lambda stage: print('[Network] '+stage, flush=True))
    (args.output/'diagnosis.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
