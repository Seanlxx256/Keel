"""Explicit one-time tokenizer preparation; runtime counting stays offline."""
import base64
import hashlib
import importlib.metadata
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from compass.progress import atomic_json
from keel.context_budget import estimate_input,validate_policy
from keel.execution import CommandRunner


def export_encoding(model_config, base_policy, output):
    import tiktoken
    output=Path(output)
    model=json.loads(Path(model_config).read_text(encoding='utf-8'))['name']
    policy=json.loads(Path(base_policy).read_text(encoding='utf-8'));validate_policy(policy)
    # Only explicit preparation may resolve/download assets. Unknown model mapping stops.
    encoding=tiktoken.encoding_for_model(model)
    data={'name':encoding.name,'pat_str':encoding._pat_str,
          'mergeable_ranks':{base64.b64encode(k).decode():v for k,v in encoding._mergeable_ranks.items()},
          'special_tokens':encoding._special_tokens}
    path=output/'tokenizer.json'
    if path.exists() or (output/'policy.json').exists():raise ValueError('Tokenizer output exists')
    atomic_json(path,data)
    policy.update(local_tokenizer=str(path.resolve()),local_tokenizer_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  require_local_tokenizer=True,recover_capacity=True)
    sample=[{'role':'user','content':'def f(x):\n    return x + 1\n中文测试'}]
    measured=estimate_input(sample,{},policy)
    if measured['estimator']!='offline_tiktoken':raise ValueError('Offline selfcheck did not use tokenizer')
    atomic_json(output/'policy.json',policy)
    atomic_json(output/'export.json',{'model':model,'encoding':encoding.name,
                'tiktoken_version':importlib.metadata.version('tiktoken'),
                'tokenizer_sha256':policy['local_tokenizer_sha256'],'sample_estimate':measured,
                'provider_calls':0,'scope':'Local text count; provider framing/schema still require safety/calibration.'})



def verify_export(output):
    output=Path(output).resolve()
    policy=json.loads((output/'policy.json').read_text(encoding='utf-8'));validate_policy(policy)
    encoding_path=Path(policy['local_tokenizer']).resolve()
    if encoding_path!=output/'tokenizer.json' or not policy.get('require_local_tokenizer'):
        raise ValueError('Preparation did not produce its strict local encoding')
    exported=json.loads((output/'export.json').read_text(encoding='utf-8'))
    identity=hashlib.sha256(encoding_path.read_bytes()).hexdigest()
    if identity!=policy['local_tokenizer_sha256'] or identity!=exported['tokenizer_sha256']:
        raise ValueError('Prepared tokenizer identity mismatch')
    return estimate_input([{'role':'user','content':'offline verification'}],{},policy)

def prepare(model_config,base_policy,output,*,install=False,timeout=180,transcripts=(),recover_from=None):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();report={'status':'running','provider_calls':0,'stages':[],
        'python':sys.executable,'input_hashes':{str(Path(p).resolve()):hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                            for p in (model_config,base_policy,*transcripts)}}
    atomic_json(output/'report.json',report)
    def stage(label,command,cap):
        remaining=timeout-(time.monotonic()-started)
        if remaining<=0:raise TimeoutError('Tokenizer preparation deadline')
        print('[Tokenizer setup] '+label,flush=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(CommandRunner().run,command,output,min(cap,remaining))
            while True:
                try:result=future.result(timeout=10);break
                except FutureTimeout:print('[Tokenizer setup] '+label+' still running',flush=True)
        atomic_json(output/(label+'-process.json'),result)
        report['stages'].append({'stage':label,'returncode':result['returncode'],'timeout':result['timeout']})
        atomic_json(output/'report.json',report)
        if result['returncode']!=0 or result['timeout']:raise RuntimeError(label+' failed; inspect saved stage output')
    try:
        if recover_from is not None and install:
            raise ValueError('Recovery must not reinstall dependencies')
        if install:
            stage('install',[sys.executable,'-m','pip','install','--disable-pip-version-check','--retries','0',
                             '--timeout','15','tiktoken>=0.7,<1'],120)
        script=Path(__file__).resolve().parents[1]/'examples/prepare_token_counting.py'
        export_command=[sys.executable,str(script),'--worker','--model-config',str(Path(model_config).resolve()),
                        '--policy',str(Path(base_policy).resolve()),'--output',str(output)]
        if recover_from is not None:
            report['recovery_source']=str(Path(recover_from).resolve())
            export_command.extend(['--recover-from',str(Path(recover_from).resolve())])
        stage('export',export_command,60)
        report['offline_selfcheck']=verify_export(output)
        if transcripts:
            replay_script=script.parent/'replay_request_capacity.py'
            replay_command=[sys.executable,str(replay_script),'--policy',str(output/'policy.json'),'--output',str(output/'replay')]
            for source in transcripts:replay_command.extend(['--transcript',str(Path(source).resolve())])
            stage('calibration',replay_command,60)
        for source,identity in report['input_hashes'].items():
            if hashlib.sha256(Path(source).read_bytes()).hexdigest()!=identity:
                raise ValueError('Tokenizer preparation input changed')
        report['status']='completed'
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__);raise
    finally:
        report['seconds']=time.monotonic()-started;atomic_json(output/'report.json',report)
    return report


def recover_encoding(model_config,base_policy,source,output):
    """Recover only verified assets; rebuilt metadata is explicitly not the lost receipt."""
    from tiktoken.model import encoding_name_for_model
    source=Path(source).resolve();output=Path(output).resolve()
    raw=(source/'tokenizer.json').read_bytes()
    old_policy=json.loads((source/'policy.json').read_text(encoding='utf-8'))
    previous=json.loads((source/'report.json').read_text(encoding='utf-8'))
    model=json.loads(Path(model_config).read_text(encoding='utf-8'))['name']
    base=json.loads(Path(base_policy).read_text(encoding='utf-8'));validate_policy(base)
    for path in (model_config,base_policy):
        absolute=str(Path(path).resolve())
        if previous['input_hashes'].get(absolute)!=hashlib.sha256(Path(path).read_bytes()).hexdigest():
            raise ValueError('Recovery input drift')
    for stage in ('export',):
        if not any(r['stage']==stage and r['returncode']==0 and not r['timeout'] for r in previous['stages']):
            raise ValueError('Source preparation stage was not completed')
    if any(r['stage']=='install' and (r['returncode']!=0 or r['timeout']) for r in previous['stages']):
        raise ValueError('Source installation stage failed')
    identity=hashlib.sha256(raw).hexdigest();data=json.loads(raw)
    if identity!=old_policy.get('local_tokenizer_sha256') or data['name']!=encoding_name_for_model(model):
        raise ValueError('Recovered encoding identity or model mapping mismatch')
    preserved={k:v for k,v in old_policy.items() if k not in
               ('local_tokenizer','local_tokenizer_sha256','require_local_tokenizer','recover_capacity')}
    expected={k:v for k,v in base.items() if k not in
              ('local_tokenizer','local_tokenizer_sha256','require_local_tokenizer','recover_capacity')}
    if preserved!=expected:raise ValueError('Recovered capacity policy differs from base')
    target=output/'tokenizer.json'
    if target.exists() or (output/'policy.json').exists():raise ValueError('Recovery output exists')
    # Copy the exact bytes. Old source and failed receipt are never modified.
    target.write_bytes(raw)
    policy={**old_policy,'local_tokenizer':str(target)}
    measured=estimate_input([{'role':'user','content':'offline recovery verification'}],{},policy)
    atomic_json(output/'policy.json',policy)
    atomic_json(output/'export.json',{'model':model,'encoding':data['name'],
        'tiktoken_version':importlib.metadata.version('tiktoken'),'tokenizer_sha256':identity,
        'sample_estimate':measured,'provider_calls':0,
        'recovery':{'source':str(source),'source_files':{
            name:hashlib.sha256((source/name).read_bytes()).hexdigest()
            for name in ('tokenizer.json','policy.json','report.json','export.json')},
            'scope':'Reconstructed metadata from verified assets/current engine; not restoration of overwritten original receipt.'}})
