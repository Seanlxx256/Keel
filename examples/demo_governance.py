"""Zero-model local runtime demonstration; no Ray/Kubernetes certification."""
import argparse
import json
from pathlib import Path
import sys

from keel.governance import ControlStore
from keel.runtime import run


def execute(output):
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    repo=output/'repo';repo.mkdir()
    (repo/'app.py').write_text('VERSION = 1\n',encoding='utf-8')
    config={'goal':'Upgrade the version without changing acceptance',
        'budget':{'max_wallclock':30},
        'governance':{'path':str(output/'control.sqlite'),'scope':'local-demo',
                      'max_tokens':10000,'max_model_calls':5,'lease_seconds':60,
                      'denied_tools':['search_code']},
        'queries':[],
        'acceptance':[[sys.executable,'-c','import app; assert app.VERSION == 2']],
        'work_items':[{'id':'upgrade','edits':[{'path':'app.py','old':'VERSION = 1','new':'VERSION = 2'}]}]}
    (output/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    print('[Governance demo] explicit edit and real local acceptance; model calls=0; budget=30s',flush=True)
    result=run(config,repo,output/'runtime')
    store=ControlStore(output/'control.sqlite',initialize=False)
    evidence=store.inspect(scope='local-demo',run_id=result['governance']['run_id'])
    (output/'control-evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    report={'status':result['status'],'model_calls':result['budget']['model_calls'],
            'runtime_result':str(output/'runtime/result.json'),'control_evidence':str(output/'control-evidence.json'),
            'scope':'Local explicit runtime + durable governance, not multi-node or sandbox validation.'}
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    report=execute(parser.parse_args().output)
    print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(0 if report['status']=='passed' else 1)
