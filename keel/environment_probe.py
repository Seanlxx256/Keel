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
import importlib, importlib.metadata as md, json, sys, traceback, shutil,pathlib
request = json.loads(sys.argv[1])
inventory = sorted((d.metadata.get('Name', ''), d.version) for d in md.distributions())
result = {'python': sys.version, 'executable':sys.executable, 'sys_path':sys.path,
 'inventory': inventory[:200], 'omitted_distributions': max(0,len(inventory)-200), 'modules': {}, 'distributions': {},'launchers':{}}
for name in ('python','pip','pytest'):
 path=shutil.which(name)
 entry={'path':path}
 if path:
  try:
   with open(path,'rb') as stream: first=stream.readline(512)
   if first.startswith(b'#!'): entry['shebang']=first.decode('utf-8',errors='replace').strip()
  except OSError: pass
 result['launchers'][name]=entry
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


PLUGIN_PROGRAM = r'''
import importlib.metadata as md,json,sys,warnings,traceback
def canonical(name): return name.lower().replace('_','-').replace('.','-')
group='setuptools_scm.version_scheme'
scheme='release-branch-semver'
providers=[]
installed=list(md.distributions())
for dist in installed:
 for entry in dist.entry_points:
  if entry.group==group and entry.name==scheme:
   providers.append((dist,entry))
result={'group':group,'scheme':scheme,'providers':[], 'dependent_distributions':{}}
for dist,entry in providers:
 name=dist.metadata.get('Name','')
 row={'distribution':name,'version':dist.version,'entry_point':entry.value}
 # Report possible dependents conservatively; no uninstall is authorized here.
 result['dependent_distributions'][name]=[
  {'name':other.metadata.get('Name',''),'requirement':requirement}
  for other in installed for requirement in (other.requires or [])
  if canonical(requirement.split(';')[0].split('[')[0].split(' ')[0].split('>')[0].split('<')[0].split('=')[0].split('!')[0].strip())==canonical(name)][:40]
 result['providers'].append(row)
try:
 import setuptools_scm
 from setuptools_scm.git import parse
 with warnings.catch_warnings():
  warnings.simplefilter('error',DeprecationWarning)
  try:
   result['baseline']={'passed':True,'value':setuptools_scm.get_version(root='/testbed',version_scheme=scheme)}
  except Exception as error:
   result['baseline']={'passed':False,'error_type':type(error).__name__,'error':str(error)[:1500]}
 version=parse('/testbed')
 for row,(dist,entry) in zip(result['providers'],providers):
  try:
   with warnings.catch_warnings():
    warnings.simplefilter('error',DeprecationWarning)
    value=entry.load()(version)
   row['isolated_call']={'passed':True,'value':str(value)}
  except Exception as error:
   row['isolated_call']={'passed':False,'error_type':type(error).__name__,'error':str(error)[:1500]}
except Exception as error:
 result['probe_error']={'error_type':type(error).__name__,'error':str(error)[:1500]}
result['scope']='Read-only provider calls with identical SCM input and DeprecationWarning-as-error; not package removal or reference recovery.'
print(json.dumps(result))
'''


def inspect_image(directory, modules, distributions, *, timeout=45, plugin_probe=False):
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
               '--entrypoint', '/opt/miniconda3/envs/testbed/bin/python', image, '-B', '-c', PLUGIN_PROGRAM if plugin_probe else PROGRAM,
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
    if len(result.stdout)>262144:
        return {'image':image,'returncode':1,'error':'Inspection output exceeds 256 KiB; narrow the inspection',
                'stdout':'','omitted_stdout_characters':len(result.stdout)}
    return {'image':image, 'restored_from_archived_recipe':restored, 'returncode':result.returncode, 'stdout':result.stdout,
            'stderr':result.stderr[-2000:], 'omitted_stdout_characters':0,
            'scope':'Fixed diagnostics in network-disabled read-only container; no host mount or credentials'}
