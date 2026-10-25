"""Move diagnostic APT archives between build backends as a checked local image."""
import hashlib
import inspect
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid


SHA=r'sha256:[a-f0-9]{64}'


def validate_artifact(value):
    fields={'schema_version','image','image_id','base_image','base_image_id','apt_command_sha256','cache_id'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema_version']!=1:
        raise ValueError('Expected exact APT archive artifact identity')
    if not re.fullmatch(r'keel-apt-archives:[a-f0-9]{32}',value['image']):
        raise ValueError('Require owned local archive image tag')
    if any(not re.fullmatch(SHA,value[k]) for k in ('image_id','base_image_id')):
        raise ValueError('Require immutable archive and base image identities')
    if not re.fullmatch(r'sweb\.env\.[A-Za-z0-9._-]+:[A-Za-z0-9._-]+',value['base_image']):
        raise ValueError('Require official local environment image')
    if not re.fullmatch(r'[a-f0-9]{64}',value['apt_command_sha256']):
        raise ValueError('Require exact APT command identity')
    expected='keel-apt-'+hashlib.sha256(value['base_image_id'].encode()).hexdigest()[:24]
    if value['cache_id']!=expected:raise ValueError('Archive cache belongs to a different base image')
    return value


EXPORT_PROGRAM=r'''
import hashlib,json,pathlib,shutil
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
source=pathlib.Path('/var/cache/apt/archives');target=pathlib.Path('/archives');target.mkdir()
rows=[];total=0
for path in sorted(source.glob('*.deb')):
 if path.is_symlink() or not path.is_file():raise RuntimeError('Nonregular archive entry')
 total+=path.stat().st_size
 if len(rows)>=2000 or total>1073741824:raise RuntimeError('Archive export resource envelope exceeded')
 shutil.copyfile(path,target/path.name)
 rows.append({'name':path.name,'bytes':path.stat().st_size,'sha256':digest(path)})
if not rows:raise RuntimeError('Diagnostic archive cache unavailable; no download dispatched')
(target/'manifest.json').write_text(json.dumps({'files':rows,'bytes':total}))
print('KEEL_ARCHIVE_EXPORT='+json.dumps({'files':len(rows),'bytes':total}),flush=True)
'''


def export_archives(diagnosis, script, output, *, timeout=300):
    """Read an existing BuildKit cache offline; never rerun APT to populate it."""
    from examples.check_repository_network import extract_apt
    from examples.swebench_bridge import run_harness
    from .evaluation_protocol import file_hash
    if type(timeout) is not int or not 30<=timeout<=900:raise ValueError('Archive export needs30..900seconds')
    diagnosis,script,output=map(Path,(diagnosis,script,output))
    saved=json.loads(diagnosis.read_text(encoding='utf-8'))
    if saved.get('status')!='apt_completed' or saved.get('source_sha256')!=file_hash(script):
        raise ValueError('Require a completed diagnosis for exactly this setup script')
    command=extract_apt(script.read_text(encoding='utf-8'))
    artifact={'schema_version':1,'image':'keel-apt-archives:'+uuid.uuid4().hex,
              'image_id':'sha256:'+'0'*64,'base_image':saved['image'],
              'base_image_id':saved['base_image_id'],
              'apt_command_sha256':hashlib.sha256(command.encode()).hexdigest(),'cache_id':saved['archive_cache_id']}
    validate_artifact(artifact)
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();report={'status':'running','model_calls':0,
        'inputs':{str(p):file_hash(p) for p in (diagnosis,script)},
        'scope':'Copy existing diagnostic archives only; APT signature/hash verification remains required in consumer'}
    from compass.progress import atomic_json
    def save():atomic_json(output/'export.json',report)
    def remaining():
        value=timeout-(time.monotonic()-started)
        if value<=0:raise TimeoutError('Archive export deadline exhausted')
        return value
    def identity(name):
        value=subprocess.run(['docker','image','inspect','--format','{{.Id}}',name],
            capture_output=True,text=True,check=True,timeout=min(8,remaining())).stdout.strip()
        if not re.fullmatch(SHA,value):raise ValueError('Invalid local image identity')
        return value
    save()
    try:
        if identity(artifact['base_image'])!=artifact['base_image_id']:raise ValueError('Base image changed')
        context=output/'context';context.mkdir()
        (context/'export_archives.py').write_text(EXPORT_PROGRAM,encoding='utf-8',newline='\n')
        dockerfile=(f"FROM {artifact['base_image']} AS collector\n"
            "COPY export_archives.py /tmp/keel_export_archives.py\n"
            f"RUN --mount=type=cache,id={artifact['cache_id']},target=/var/cache/apt/archives,sharing=locked "
            'python -B /tmp/keel_export_archives.py\nFROM scratch\nCOPY --from=collector /archives/ /archives/\n')
        (context/'Dockerfile').write_text(dockerfile,encoding='utf-8',newline='\n')
        process=run_harness(['docker','build','--pull=false','--network=none','--progress=plain',
            '--tag',artifact['image'],str(context.resolve())],cwd=output,log_path=output/'build.log',timeout=remaining())
        if process.returncode:raise RuntimeError('Archive export build unavailable; no APT retry')
        artifact['image_id']=identity(artifact['image'])
        if identity(artifact['base_image'])!=artifact['base_image_id']:raise ValueError('Base image changed during export')
        for path,expected in report['inputs'].items():
            if file_hash(Path(path))!=expected:raise ValueError('Archive export evidence changed')
        validate_artifact(artifact);atomic_json(output/'artifact.json',artifact)
        report.update(status='completed',artifact_sha256=file_hash(output/'artifact.json'),artifact=artifact)
    except Exception as error:
        report.update(status='unavailable',error_type=type(error).__name__,error=str(error)[:1000])
    finally:
        report['seconds']=round(time.monotonic()-started,3);save()
    return report


RESTORE_PROGRAM=r'''
import hashlib,json,pathlib,re,shutil,sys
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
root=pathlib.Path('/tmp/keel-apt-archives');cache=pathlib.Path('/var/cache/apt/archives')
clean=pathlib.Path('/etc/apt/apt.conf.d/docker-clean');backup=root/'docker-clean.backup'
manifest=json.loads((root/'manifest.json').read_text());rows=manifest['files']
if not isinstance(rows,list) or not 1<=len(rows)<=2000:raise RuntimeError('Invalid archive inventory')
names=set();total=0
for row in rows:
 name=row['name']
 if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.+%~:-]+\.deb',name) or name in names:raise RuntimeError('Invalid archive path')
 names.add(name);path=root/name
 if path.is_symlink() or not path.is_file() or path.stat().st_size!=row['bytes']:raise RuntimeError('Archive size/type changed')
 total+=path.stat().st_size
 if total>1073741824 or digest(path)!=row['sha256']:raise RuntimeError('Archive bytes changed')
if total!=manifest['bytes']:raise RuntimeError('Archive total changed')
if sys.argv[1]=='before':
 if backup.exists():raise RuntimeError('Unfinished archive cleanup')
 cache.mkdir(parents=True,exist_ok=True)
 for row in rows:
  target=cache/row['name']
  if target.is_symlink():raise RuntimeError('Unsafe APT cache target')
  if target.exists() and digest(target)!=row['sha256']:raise RuntimeError('Conflicting APT cache entry')
 for row in rows:shutil.copyfile(root/row['name'],cache/row['name'])
 if clean.exists():shutil.copyfile(clean,backup);clean.unlink()
 print('KEEL_APT_ARCHIVE_BRIDGE='+json.dumps({'injected_files':len(rows),'bytes':total,'scope':'Validated archives supplied; APT decides reuse and verifies repository checksums'}),flush=True)
elif sys.argv[1]=='after':
 if backup.exists():shutil.copyfile(backup,clean);backup.unlink()
 for row in rows:
  path=cache/row['name']
  if path.is_file() and not path.is_symlink():path.unlink()
else:raise RuntimeError('Invalid archive operation')
'''


def apply_archive_policy(spec,artifact):
    from examples.check_repository_network import extract_apt
    validate_artifact(artifact)
    key=hashlib.sha256(json.dumps(artifact,sort_keys=True).encode()).hexdigest()[:16]
    if getattr(spec,'_keel_apt_archives',None)==key:return spec
    if getattr(spec,'_keel_apt_archives',None):raise ValueError('Cannot stack archive artifacts')
    if spec.env_image_key!=artifact['base_image']:raise ValueError('Archive base does not match recipe environment')
    command=extract_apt('\n'.join(spec.repo_script_list))
    if hashlib.sha256(command.encode()).hexdigest()!=artifact['apt_command_sha256']:
        raise ValueError('Archive workload differs from official recipe')
    if any(re.match(r'^\s*trap\s',line) for line in spec.repo_script_list):
        raise ValueError('Unsupported existing cleanup trap; do not overwrite')
    marker='# Keel APT archives '+key
    before='python -B -c '+shlex.quote(RESTORE_PROGRAM)+' before'
    after='python -B -c '+shlex.quote(RESTORE_PROGRAM)+' after'
    trap='trap '+shlex.quote('keel_apt_status=$?; '+after+'; exit "$keel_apt_status"')+' EXIT'
    result=[]
    for line in spec.repo_script_list:
        if line.strip()==command:
            result.extend([marker,before,trap,line,after,'trap - EXIT'])
        else:result.append(line)
    spec.repo_script_list=result;spec.instance_image_tag+='-archives-'+key;spec._keel_apt_archives=key
    return spec


def inject_archive_copy(dockerfile,artifact):
    validate_artifact(artifact)
    lines=dockerfile.splitlines(True)
    positions=[i for i,line in enumerate(lines) if line.startswith('FROM ')]
    if len(positions)!=1:raise ValueError('Require one official instance build stage')
    lines.insert(positions[0]+1,'COPY --from='+artifact['image']+' /archives/ /tmp/keel-apt-archives/\n')
    return ''.join(lines)


def install_archive_policy(artifact):
    """Restricted adapter in harness child; no replacing official test executor."""
    import sys
    import swebench.harness.test_spec.test_spec as specs
    import swebench.harness.docker_build as builds
    validate_artifact(artifact)
    original=specs.make_test_spec;builder=builds.build_image
    def make(*args,**kwargs):return apply_archive_policy(original(*args,**kwargs),artifact)
    def build(*args,**kwargs):
        bound=inspect.signature(builder).bind(*args,**kwargs)
        scripts=bound.arguments['setup_scripts']
        imported='# Keel APT archives ' in scripts.get('setup_repo.sh','')
        def verify():
            client=bound.arguments['client']
            for name,expected in [(artifact['image'],artifact['image_id']),(artifact['base_image'],artifact['base_image_id'])]:
                if client.api.inspect_image(name)['Id']!=expected:raise ValueError('Archive/base image identity changed')
        if imported:
            verify()
            bound.arguments['dockerfile']=inject_archive_copy(bound.arguments['dockerfile'],artifact)
        result=builder(*bound.args,**bound.kwargs)
        if imported:verify()
        return result
    specs.make_test_spec=make;builds.build_image=build
    for name,module in list(sys.modules.items()):
        if name.startswith('swebench.harness.') and module is not None:
            if getattr(module,'make_test_spec',None) is original:module.make_test_spec=make
            if getattr(module,'build_image',None) is builder:module.build_image=build
