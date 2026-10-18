"""Fixed diagnostic program executed only in a network-disabled harness container."""
import json
import re
import subprocess
import uuid


def validate_inspection(modules, distributions):
    if (not isinstance(modules, list) or not isinstance(distributions, list) or
            not 1 <= len(modules)+len(distributions) <= 12 or
            any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', x) for x in modules) or
            any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', x) for x in distributions)):
        raise ValueError('Inspection requires 1..12 module/distribution identifiers, not commands or paths')


PROGRAM = r'''
import importlib, importlib.metadata as md, json, sys, traceback
request = json.loads(sys.argv[1])
inventory = sorted((d.metadata.get('Name', ''), d.version) for d in md.distributions())
result = {'python': sys.version, 'inventory': inventory[:200], 'omitted_distributions': max(0,len(inventory)-200), 'modules': {}, 'distributions': {}}
for name in request['modules']:
    try:
        module = importlib.import_module(name)
        result['modules'][name] = {'file': getattr(module,'__file__',None), 'path': list(getattr(module,'__path__',[]))}
    except Exception:
        result['modules'][name] = {'error': traceback.format_exc()[-3000:]}
for name in request['distributions']:
    try:
        dist = md.distribution(name)
        result['distributions'][name] = {'version':dist.version, 'requires':(dist.requires or [])[:40], 'location':str(dist.locate_file('')), 'entry_points':[str(x) for x in dist.entry_points][:30]}
    except Exception:
        result['distributions'][name] = {'error':traceback.format_exc()[-1000:]}
print(json.dumps(result))
'''


def inspect_image(directory, modules, distributions, *, timeout=45):
    validate_inspection(modules, distributions)
    images = sorted((directory/'logs/build_images/instances').glob('*/Dockerfile'))
    if len(images) != 1:
        raise ValueError('Expected one archived instance image recipe for inspection')
    name, tag = images[0].parent.name.rsplit('__', 1)
    image = name + ':' + tag
    container = 'keel-env-probe-' + uuid.uuid4().hex
    command = ['docker', 'run', '--rm', '--name', container, '--pull', 'never', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges', '--pids-limit', '128', '--memory', '1g',
               '--tmpfs', '/tmp:rw,size=64m', '--workdir', '/testbed',
               '--entrypoint', '/opt/miniconda3/envs/testbed/bin/python', image, '-B', '-c', PROGRAM,
               json.dumps({'modules': modules, 'distributions': distributions})]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        restored = False
        if result.returncode == 125 and 'No such image' in result.stderr:
            # Official evaluation may have removed this image after reporting.
            # Restore only the exact archived recipe, never ask the model for build commands.
            context = images[0].parent
            log = directory/'inspection-image-restore.log'
            with log.open('wb') as stream:
                build = subprocess.run(['docker','build','--pull=false','--tag',image,
                    '--file',str(images[0].resolve()),str(context.resolve())],
                    stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
            if build.returncode != 0:
                return {'image':image,'returncode':build.returncode,'error':'Archived image restoration failed',
                        'restore_log':str(log),'stderr':log.read_text(encoding='utf-8',errors='replace')[-2000:]}
            restored = True
            result = subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    finally:
        try:
            subprocess.run(['docker','rm','-f',container],capture_output=True,timeout=10)
        except (OSError,subprocess.TimeoutExpired):
            pass
    return {'image':image, 'restored_from_archived_recipe':restored, 'returncode':result.returncode, 'stdout':result.stdout[:14000],
            'stderr':result.stderr[-2000:], 'omitted_stdout_characters':max(0,len(result.stdout)-14000),
            'scope':'Fixed diagnostics in network-disabled read-only container; no host mount or credentials'}
