"""Execute a predeclared local training/endpoint comparison; never choose a winner."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.scout_tokenizer import file_hash
from keel.scout_tokenizer_setup import observed_stage


def execute(plan_path):
    plan_path=Path(plan_path);plan=json.loads(plan_path.read_text());output=Path(plan['output'])
    output.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    report={'status':'running','protocol_sha256':file_hash(plan_path),'stages':[],
        'scope':plan.get('scope','Exposed development epoch comparison; no endpoint selection or independent score'),
        'production_promoted':False,'selected_checkpoint':None}
    atomic_json(output/'report.json',report)
    try:
        for stage in plan['stages']:
            remaining=plan['max_seconds']-(time.monotonic()-started)
            if remaining<=0:raise TimeoutError('Comparison shared deadline')
            result=observed_stage(stage['command'],output,min(stage['cap_seconds'],remaining),stage['name'])
            report['stages'].append({'name':stage['name'],'returncode':result['returncode'],'timeout':result['timeout']})
            atomic_json(output/'report.json',report)
            if result['returncode']!=0 or result['timeout']:raise RuntimeError('Stage incomplete: '+stage['name'])
        report['comparisons']={}
        for name,path in plan['evaluation_reports'].items():
            data=json.loads(Path(path).read_text())
            if data['status']!='completed':raise ValueError('Missing completed endpoint evaluation')
            report['comparisons'][name]={'summary':data['summary'],'report':path,'sha256':file_hash(path)}
        report['status']='completed'
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__);raise
    finally:
        report['seconds']=round(time.monotonic()-started,3);atomic_json(output/'report.json',report)
    print(json.dumps({'status':report['status'],'comparisons':report['comparisons'],'report':str(output/'report.json')}))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plan',type=Path,required=True)
    execute(parser.parse_args().plan)
