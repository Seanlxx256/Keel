"""Verified, resumable archival of explicitly approved intermediate checkpoints."""
import hashlib
import json
import math
from pathlib import Path
import time
import zipfile

from compass.progress import atomic_json


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def safe_path(root,relative):
    root=Path(root).resolve();relative=relative.replace('\\','/')
    parts=relative.split('/')
    if not parts or any(p in ('','..','.') or ':' in p for p in parts):raise ValueError('Unsafe archive path')
    current=root
    for part in parts:
        current=current/part
        if current.exists():
            info=current.lstat()
            if current.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('Reparse point in archive path')
    if not current.resolve().is_relative_to(root):raise ValueError('Archive path escapes workspace')
    return current


def build_manifest(workspace,proposal):
    root=Path(workspace).resolve();files={};directories=[];inputs={};finals={}
    if len(proposal['groups'])!=2:raise ValueError('Require the two approved training groups')
    seen=set()
    for group in proposal['groups']:
        relative='.keel/finetuning/'+group['training'].replace('\\','/')
        training=safe_path(root,relative)
        if relative in seen:raise ValueError('Duplicate archive group')
        seen.add(relative)
        if not relative.startswith('.keel/finetuning/scout-representation-comparison-v1/results/'):
            raise ValueError('Outside approved experiment')
        if relative.split('/')[4] not in ('numbered_end','id_free_end'):
            raise ValueError('Outside approved completed cells')
        receipt=training/'training.json';parent=training.parent/'report.json'
        data=json.loads(receipt.read_text());outer=json.loads(parent.read_text())
        final=group['final_step']
        if (final!=168 or data['status']!='passed' or outer['status']!='passed' or
            len(data['steps'])!=final or outer['training_sha256']!=digest(receipt)):
            raise ValueError('Require completed hash-bound 168-step training')
        for path in (receipt,parent):inputs[path.relative_to(root).as_posix()]=digest(path)
        for number in range(1,final+1):
            rel=relative+'/step-'+str(number);folder=safe_path(root,rel)
            entries=list(folder.iterdir())
            if not entries or any(not p.is_file() or p.is_symlink() for p in entries):
                raise ValueError('Require flat regular checkpoint files')
            expected=data['steps'][number-1]['checkpoint_files']
            if {p.name for p in entries}!=set(expected)|{'step.json'}:
                raise ValueError('Unexpected checkpoint files')
            for path in entries:
                path=safe_path(root,path.relative_to(root).as_posix())
                h=digest(path)
                if path.name in expected and h!=expected[path.name]:raise ValueError('Checkpoint hash drift')
                key=path.relative_to(root).as_posix();value={'sha256':h,'size':path.stat().st_size}
                if number==final:finals[key]=value
                else:files[key]=value
            if number<final:directories.append(rel)
    return {'version':1,'workspace':str(root),'files':files,'directories':directories,'inputs':inputs,'finals':finals}


def validate_sources(manifest,allow_missing=False):
    root=Path(manifest['workspace'])
    for relative,h in manifest['inputs'].items():
        if digest(safe_path(root,relative))!=h:raise ValueError('Training receipt drift')
    for relative,v in manifest['finals'].items():
        if digest(safe_path(root,relative))!=v['sha256']:raise ValueError('Final checkpoint drift')
    for relative in manifest['directories']:
        folder=safe_path(root,relative)
        if folder.exists():
            allowed={name for name in manifest['files'] if name.rsplit('/',1)[0]==relative}
            if any(p.relative_to(root).as_posix() not in allowed for p in folder.iterdir()):
                raise ValueError('Unexpected file appeared in archived checkpoint')
        elif not allow_missing:raise ValueError('Source checkpoint missing before archival')
    for relative,v in manifest['files'].items():
        path=safe_path(root,relative)
        if not path.exists() and allow_missing:continue
        if digest(path)!=v['sha256']:raise ValueError('Source checkpoint changed')


def verify_zip(archive,manifest,check=lambda:None):
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(set(names))!=len(names) or set(names)!=set(manifest['files'])|{'archive-manifest.json'}:
            raise ValueError('Archive member coverage differs')
        if json.loads(z.read('archive-manifest.json'))!=manifest:raise ValueError('Archive manifest differs')
        for relative,v in manifest['files'].items():
            check();h=hashlib.sha256();size=0
            with z.open(relative) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):
                    check();size+=len(block);h.update(block)
            if h.hexdigest()!=v['sha256'] or size!=v['size']:raise ValueError('Archive content checksum differs')


def archive_checkpoints(workspace,proposal_path,archive,record,*,seconds=900):
    if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or seconds<=0:
        raise ValueError('Positive finite archive deadline required')
    root=Path(workspace).resolve();proposal_path=Path(proposal_path);archive=Path(archive);record=Path(record)
    started=time.monotonic()
    def check():
        if time.monotonic()-started>seconds:raise TimeoutError('Archive deadline; completed archive/cleanup remains reusable')
    if archive.resolve().is_relative_to(root):raise ValueError('Archive must be outside workspace to free its disk')
    if not record.resolve().is_relative_to(root):raise ValueError('Record must stay in workspace')
    proposal_hash=digest(proposal_path);manifest_path=record/'manifest.json'
    record.mkdir(parents=True,exist_ok=True)
    identity={'proposal_sha256':proposal_hash,'archive':str(archive.resolve()),'workspace':str(root)}
    identity_path=record/'identity.json'
    if identity_path.exists():
        if json.loads(identity_path.read_text())!=identity:raise ValueError('Archive recovery identity drift')
        manifest=json.loads(manifest_path.read_text())
    else:
        if archive.exists():raise ValueError('Existing destination without trusted local manifest')
        manifest=build_manifest(root,json.loads(proposal_path.read_text()))
        atomic_json(manifest_path,manifest);atomic_json(identity_path,identity)
    state={'status':'verifying_sources','archive':str(archive),'deleted_directories':0}
    atomic_json(record/'report.json',state)
    try:
        # Existing complete archives permit cleanup recovery after interruption.
        validate_sources(manifest,allow_missing=archive.exists());check()
        archive.parent.mkdir(parents=True,exist_ok=True)
        partial=archive.with_suffix(archive.suffix+'.partial')
        if not archive.exists():
            if partial.exists():
                verify_zip(partial,manifest,check)
            else:
                state['status']='archiving';atomic_json(record/'report.json',state)
                with zipfile.ZipFile(partial,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
                    z.writestr('archive-manifest.json',json.dumps(manifest,sort_keys=True))
                    for index,(relative,v) in enumerate(manifest['files'].items()):
                        check();source=safe_path(root,relative)
                        if digest(source)!=v['sha256']:raise ValueError('Source changed during archive')
                        with source.open('rb') as stream,z.open(relative,'w',force_zip64=True) as target:
                            for block in iter(lambda:stream.read(1024*1024),b''):check();target.write(block)
                        if index%200==0:print(f'[Archive] {index+1}/{len(manifest["files"])} files',flush=True)
                verify_zip(partial,manifest,check)
            partial.rename(archive)
        verify_zip(archive,manifest,check)
        validate_sources(manifest,allow_missing=True);check()
        state.update(status='verified_cleanup',archive_sha256=digest(archive),manifest_sha256=digest(manifest_path))
        atomic_json(record/'report.json',state)
        # No shell deletion or recursive removal: unlink only manifest-listed
        # regular files inside the two prevalidated intermediate checkpoint roots.
        for index,relative in enumerate(manifest['directories']):
            check();folder=safe_path(root,relative)
            if folder.exists():
                for name,v in manifest['files'].items():
                    if name.rsplit('/',1)[0]!=relative:continue
                    path=safe_path(root,name)
                    if path.exists():
                        if digest(path)!=v['sha256']:raise ValueError('Source changed before cleanup')
                        path.unlink()
                folder.rmdir()
            state['deleted_directories']=index+1
            atomic_json(record/'report.json',state)
            if index%20==0:print(f'[Cleanup] {index+1}/{len(manifest["directories"])} checkpoints',flush=True)
        validate_sources(manifest,allow_missing=True)
        state.update(status='completed',archived_source_bytes=sum(v['size'] for v in manifest['files'].values()),archive_bytes=archive.stat().st_size)
    except BaseException as error:
        state.update(status='incomplete',error_type=type(error).__name__,error=str(error));raise
    finally:
        state['seconds']=time.monotonic()-started;atomic_json(record/'report.json',state)
    return state


def restore_checkpoint(record,relative_directory,*,seconds=900):
    if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or seconds<=0:
        raise ValueError('Positive finite restore deadline required')
    started=time.monotonic()
    def check():
        if time.monotonic()-started>seconds:raise TimeoutError('Restore deadline; partial files preserved')
    record=Path(record);identity=json.loads((record/'identity.json').read_text());manifest=json.loads((record/'manifest.json').read_text())
    if relative_directory not in manifest['directories']:raise ValueError('Checkpoint outside archived selection')
    archive=Path(identity['archive']);verify_zip(archive,manifest,check)
    root=Path(manifest['workspace']);folder=safe_path(root,relative_directory);folder.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for name,v in manifest['files'].items():
            if name.rsplit('/',1)[0]!=relative_directory:continue
            path=safe_path(root,name)
            if path.exists():
                if digest(path)!=v['sha256']:raise ValueError('Restore would overwrite changed file')
                continue
            temporary=path.with_name(path.name+'.restore-partial')
            with z.open(name) as source,temporary.open('xb') as target:
                for block in iter(lambda:source.read(1024*1024),b''):check();target.write(block)
            if digest(temporary)!=v['sha256']:raise ValueError('Restore checksum differs')
            temporary.rename(path)
    return str(folder)
