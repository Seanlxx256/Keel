"""Isolated, bounded tokenizer preparation with explicit verified recovery."""
import json
import os
from pathlib import Path
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from compass.progress import atomic_json
from .execution import CommandRunner
from .scout_tokenizer import MODEL, REVISION, REQUIREMENTS, file_hash, verify_assets


def observed_stage(command,output,timeout,label):
    """Shared process deadline, heartbeat and separate process receipt."""
    print('[Scout preparation] '+label,flush=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(CommandRunner().run,command,output,timeout)
        while True:
            try:result=future.result(timeout=10);break
            except FutureTimeout:print('[Scout preparation] '+label+' still running',flush=True)
    atomic_json(Path(output)/(label+'-process.json'),result)
    return result


def adopt_completed_check(dataset,assets,source,output):
    """Reconstruct setup metadata from a completed, hash-matching offline check."""
    dataset,assets,source,output=map(lambda p:Path(p).resolve(),(dataset,assets,source,output))
    check=json.loads((source/'check.json').read_text())
    process=json.loads((source/'check-process.json').read_text())
    exported=json.loads((dataset/'export.json').read_text());verified=verify_assets(assets)
    if (process['returncode']!=0 or process['timeout'] or check['status']!='passed' or
        check['model']!=MODEL or check['revision']!=REVISION or check['tokenizer_assets']!=verified or
        exported['status']!='exported_development_only' or check['dataset_sha256']!=file_hash(dataset/'development.jsonl') or
        exported['dataset_sha256']!=check['dataset_sha256'] or len(check['samples'])!=exported['sample_count']):
        raise ValueError('Require matching completed real tokenizer check')
    output.mkdir(parents=True,exist_ok=False);(output/'check.json').write_bytes((source/'check.json').read_bytes())
    report={'status':'passed','identity':{'model':MODEL,'revision':REVISION,'requirements':list(REQUIREMENTS),
        'inputs':{name:file_hash(dataset/name) for name in ('export.json','development.jsonl')}},
        'assets':str(assets),'assets_sha256':file_hash(assets/'assets.json'),'check_sha256':file_hash(output/'check.json'),
        'migration':{'source':str(source),'check_sha256':file_hash(source/'check.json'),
            'process_sha256':file_hash(source/'check-process.json'),
            'scope':'Reconstructed metadata around completed check, not a new tokenizer execution/environment install'},
        'model_calls':0,'weight_updates':0}
    atomic_json(output/'report.json',report);return report


def prepare(dataset,output,*,timeout=600,recover_from=None):
    dataset=Path(dataset).resolve();output=Path(output).resolve()
    identity={'model':MODEL,'revision':REVISION,'requirements':list(REQUIREMENTS),
              'inputs':{name:file_hash(dataset/name) for name in ('export.json','development.jsonl')}}
    old=None
    if recover_from:
        recover_from=Path(recover_from).resolve()
        old=json.loads((recover_from/'report.json').read_text(encoding='utf-8'))
        if old['identity']!=identity:raise ValueError('Recovery inputs/configuration changed')
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    env=output/'env';python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    assets=output/'assets'
    report={'status':'running','identity':identity,'stages':[],'model_calls':0,'weight_updates':0}
    if old:report['migration']={'source':str(recover_from),'report_sha256':file_hash(recover_from/'report.json')}
    atomic_json(output/'report.json',report)
    worker=Path(__file__).resolve().parents[1]/'examples/scout_tokenizer_worker.py'
    def stage(name,command,cap):
        remaining=timeout-(time.monotonic()-started)
        if remaining<=0:raise TimeoutError('Preparation deadline')
        result=observed_stage(command,output,min(cap,remaining),name)
        report['stages'].append({'name':name,'returncode':result['returncode'],'timeout':result['timeout']})
        atomic_json(output/'report.json',report)
        if result['returncode']!=0 or result['timeout']:raise RuntimeError(name+' failed; inspect stage output')
    try:
        if old and old.get('environment_sha256'):
            receipt_path=recover_from/'environment.json'
            if file_hash(receipt_path)!=old['environment_sha256']:raise ValueError('Environment receipt changed')
            previous=json.loads(receipt_path.read_text(encoding='utf-8'));python=Path(previous['python'])
            if file_hash(python)!=previous['python_sha256']:raise ValueError('Recovered interpreter changed')
        else:
            stage('venv',[sys.executable,'-m','venv',str(env)],60)
            stage('install',[str(python),'-m','pip','--isolated','install','--index-url','https://pypi.org/simple',
                  '--disable-pip-version-check','--retries','0','--timeout','15',*REQUIREMENTS],240)
        stage('environment',[str(python),str(worker),'environment','--output',str(output)],30)
        current=json.loads((output/'environment.json').read_text(encoding='utf-8'))
        if old and old.get('environment_sha256') and current!=previous:raise ValueError('Recovered package inventory changed')
        report['environment_sha256']=file_hash(output/'environment.json')
        atomic_json(output/'report.json',report)
        if old and old.get('assets_sha256'):
            assets=Path(old['assets'])
            if file_hash(assets/'assets.json')!=old['assets_sha256']:raise ValueError('Asset receipt changed')
            verify_assets(assets)
        else:
            stage('download',[str(python),str(worker),'download','--output',str(output),'--assets',str(assets),
                              '--cache',str(output.parent/'hf-cache')],180)
        verify_assets(assets)
        report.update(assets=str(assets),assets_sha256=file_hash(assets/'assets.json'))
        atomic_json(output/'report.json',report)
        stage('check',[str(python),str(worker),'check','--output',str(output),'--assets',str(assets),'--dataset',str(dataset)],60)
        check=json.loads((output/'check.json').read_text(encoding='utf-8'))
        if check['status']!='passed':raise ValueError('Tokenizer check did not pass')
        if identity['inputs']!={name:file_hash(dataset/name) for name in identity['inputs']}:
            raise ValueError('Dataset changed during preparation')
        report.update(status='passed',check_sha256=file_hash(output/'check.json'))
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__)
        raise
    finally:
        report['seconds']=round(time.monotonic()-started,3);atomic_json(output/'report.json',report)
    return report
