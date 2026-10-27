"""Bounded preparation of a LoRA smoke, reusing an explicit read-only Torch source."""
import json
from pathlib import Path
import sys
import time
from compass.progress import atomic_json
from .scout_lora import PINS,training_inputs,verify_weights,planned_updates,validate_objective
from .scout_tokenizer import file_hash,MODEL,REVISION
from .scout_tokenizer_setup import observed_stage


def prepare(dataset,tokenizer_run,torch_site,output,*,timeout=1800,recover_from=None,reuse_preparation=None,epochs=1,max_updates=None,reproducibility='legacy',objective='generation',score_representation='legacy',train_timeout=600,environment_timeout=60):
    from .scout_reproducibility import validate_policy
    validate_policy(reproducibility)
    validate_objective(objective)
    from .scout_candidate_scoring import validate_score_representation
    validate_score_representation(score_representation,objective)
    if (isinstance(train_timeout,bool) or not isinstance(train_timeout,(int,float)) or
            not __import__('math').isfinite(train_timeout) or train_timeout<=0):
        raise ValueError('Positive finite training stage timeout required')
    if (isinstance(environment_timeout,bool) or not isinstance(environment_timeout,(int,float)) or
            not __import__('math').isfinite(environment_timeout) or environment_timeout<=0):
        raise ValueError('Positive finite environment stage timeout required')
    if type(epochs) is not int or epochs<1:raise ValueError('Positive explicit epochs required')
    if recover_from and reuse_preparation:raise ValueError('Choose strict recovery or explicit preparation migration')
    dataset,tokenizer_run,torch_site,output=map(lambda p:Path(p).resolve(),(dataset,tokenizer_run,torch_site,output))
    training_inputs(dataset,tokenizer_run)
    count=json.loads((dataset/'export.json').read_text())['sample_count']
    expected=planned_updates(count,epochs,max_updates)
    if not (torch_site/'torch/__init__.py').is_file():raise ValueError('Explicit existing Torch site required')
    identity={'model':MODEL,'revision':REVISION,'dataset':file_hash(dataset/'development.jsonl'),'tokenizer_report':file_hash(tokenizer_run/'report.json'),
        'pins':list(PINS),'torch_site':str(torch_site),'torch_source':file_hash(torch_site/'torch/__init__.py'),'epochs':epochs,'max_updates':max_updates,'reproducibility':reproducibility,'objective':objective,'score_representation':score_representation}
    old=None
    if recover_from or reuse_preparation:
        migration=bool(reuse_preparation)
        recover_from=recover_from or reuse_preparation
        recover_from=Path(recover_from).resolve();old=json.loads((recover_from/'report.json').read_text())
        previous_identity={**old['identity'],'epochs':old['identity'].get('epochs',1),'max_updates':old['identity'].get('max_updates'),
                           'reproducibility':old['identity'].get('reproducibility','legacy'),'objective':old['identity'].get('objective','generation'),
                           'score_representation':old['identity'].get('score_representation','legacy')}
        if migration:
            fields=('model','revision','pins','torch_site','torch_source')
            if any(previous_identity[k]!=identity[k] for k in fields):raise ValueError('Preparation migration environment/model drift')
        elif previous_identity!=identity:raise ValueError('Training recovery input drift')
    output.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    report={'status':'running','identity':identity,'stages':[],'train_timeout':train_timeout,'environment_timeout':environment_timeout,'scope':'Development gradient/resource smoke, not independent evaluation'}
    report['model_cache']=old.get('model_cache',str(output.parent/'model-cache')) if old else str(output.parent/'model-cache')
    if reuse_preparation:
        report['preparation_migration']={'source':str(recover_from),'old_identity':old['identity'],
            'new_identity':identity,'scope':'Reuse dependencies and weights only; fresh base-model training with explicit changed data/epochs'}
    atomic_json(output/'report.json',report)
    script=Path(__file__).resolve().parents[1]/'examples/run_scout_lora.py'
    def stage(name,command,cap):
        remaining=timeout-(time.monotonic()-started)
        if remaining<=0:raise TimeoutError('Training preparation deadline')
        result=observed_stage(command,output,min(cap,remaining),name)
        report['stages'].append({'name':name,'returncode':result['returncode'],'timeout':result['timeout']})
        atomic_json(output/'report.json',report)
        if result['returncode']!=0 or result['timeout']:raise RuntimeError(name+' failed; preserve stage receipts')
    try:
        if old and old.get('environment_sha256'):
            if file_hash(recover_from/'environment.json')!=old['environment_sha256']:raise ValueError('Environment receipt drift')
            previous=json.loads((recover_from/'environment.json').read_text());python=Path(previous['python'])
            if file_hash(python)!=previous['python_sha256']:raise ValueError('Recovered interpreter changed')
            report['migration']={'source':str(recover_from),'report_sha256':file_hash(recover_from/'report.json'),
                                 'scope':'Preparation reuse; training restarts from base, not optimizer resume'}
        elif old and all(any(s['name']==name and s['returncode']==0 and not s['timeout'] for s in old['stages'])
                         for name in ('venv','install')):
            # Installation can complete before inventory/preflight fails. Recheck
            # that environment using current code instead of reinstalling it.
            env=recover_from/'env';python=env/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
            site=env/('Lib/site-packages' if sys.platform=='win32' else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
            if (site/'keel-torch-source.pth').read_text(encoding='utf-8').strip()!=str(torch_site):
                raise ValueError('Recovered Torch source changed')
            for label in ('venv','install'):
                process=json.loads((recover_from/(label+'-process.json')).read_text())
                if process['returncode']!=0 or process['timeout']:raise ValueError('Incomplete source preparation')
            report['migration']={'source':str(recover_from),'report_sha256':file_hash(recover_from/'report.json'),
                'installation_process_sha256':file_hash(recover_from/'install-process.json'),
                'scope':'Completed install reused; current imports/inventory/CUDA rechecked before download'}
        else:
            env=output/'env';python=env/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
            stage('venv',[sys.executable,'-m','venv',str(env)],60)
            site=env/('Lib/site-packages' if sys.platform=='win32' else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
            # Read-only reuse of installed Torch/CUDA libraries; never install into that source.
            (site/'keel-torch-source.pth').write_text(str(torch_site)+'\n',encoding='utf-8')
            stage('install',[str(python),'-m','pip','--isolated','install','--index-url','https://pypi.org/simple',
                '--disable-pip-version-check','--retries','0','--timeout','15',*PINS],300)
        stage('environment',[str(python),str(script),'environment','--output',str(output)],environment_timeout)
        if old and old.get('environment_sha256') and json.loads((output/'environment.json').read_text())!=previous:
            raise ValueError('Recovered environment changed')
        report['environment_sha256']=file_hash(output/'environment.json');atomic_json(output/'report.json',report)
        weights=output/'weights'
        if old and old.get('weights_receipt_sha256'):
            weights=Path(old['weights'])
            if file_hash(weights/'weights.json')!=old['weights_receipt_sha256']:raise ValueError('Weight receipt changed')
            verify_weights(json.loads((weights/'weights.json').read_text()))
        else:
            stage('download',[str(python),str(script),'download','--output',str(weights),'--cache',report['model_cache']],900)
        report.update(weights=str(weights),weights_receipt_sha256=file_hash(weights/'weights.json'))
        atomic_json(output/'report.json',report)
        command=[str(python),str(script),'train','--output',str(output/'training'),'--dataset',str(dataset),
            '--tokenizer-run',str(tokenizer_run),'--weights',str(weights/'weights.json'),'--epochs',str(epochs)]
        if max_updates is not None:command+=['--max-updates',str(max_updates)]
        command+=['--reproducibility',reproducibility]
        command+=['--objective',objective]
        command+=['--score-representation',score_representation]
        stage('train',command,train_timeout)
        training=json.loads((output/'training/training.json').read_text())
        if training.get('reproducibility','legacy')!=reproducibility:raise ValueError('Training reproducibility policy drift')
        if training.get('objective','generation')!=objective:raise ValueError('Training objective drift')
        if training.get('score_representation','legacy')!=score_representation:raise ValueError('Training score representation drift')
        count=training.get('sample_count',len(training['steps']))
        if training['status']!='passed' or len(training['steps'])!=expected or training.get('expected_steps',expected)!=expected:raise ValueError('Planned training incomplete')
        report.update(status='passed',training_sha256=file_hash(output/'training/training.json'))
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__);raise
    finally:
        report['seconds']=round(time.monotonic()-started,3);atomic_json(output/'report.json',report)
    return report
