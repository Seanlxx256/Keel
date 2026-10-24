"""Zero-model paired acquisition on an exact failed URL; no source mutation."""
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .evaluation_protocol import file_hash
from .network_recovery import failed_workload_inputs
from .network_probe import APT_PROBE,build_probe


def compare_transports(previous,script,image,output,*,timeout=200,url_index=0,probe=None,identity=None):
    if type(timeout) is not int or not 180<=timeout<=300:
        raise ValueError('Comparison requires180..300seconds')
    initial,paths,_,urls=failed_workload_inputs(previous,script,image)
    if type(url_index) is not int or not 0<=url_index<len(urls):
        raise ValueError('Choose supplied failed URL index')
    expected=initial.get('base_image_id')
    if not isinstance(expected,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',expected):
        raise ValueError('Require immutable failed workload base identity')
    inputs={str(p):file_hash(p) for p in [previous/'diagnosis.json',script,*paths]}
    probe=probe or build_probe
    if identity is None:
        def identity():
            return subprocess.run(['docker','image','inspect','--format','{{.Id}}',image],
                capture_output=True,text=True,check=True,timeout=10).stdout.strip()
    output.mkdir(parents=True,exist_ok=False)
    deadline=time.monotonic()+timeout
    report={'status':'checking','model_calls':0,'failed_url':urls[url_index],'url_index':url_index,'base_image_id':expected,
            'inputs':inputs,'observations':[],
            'scope':'Paired exact-path APT acquisitions only; no source/proxy change or workload/reference recovery'}
    def save():(output/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    def check():
        if any(file_hash(Path(p))!=value for p,value in inputs.items()):
            raise ValueError('Comparison input changed')
        if identity()!=expected:raise ValueError('Base image identity changed')
    save()
    try:
        target=urlsplit(urls[url_index])
        for scheme in ('http','https'):
            if deadline-time.monotonic()<85:
                report['status']='budget_exhausted';return report
            check()
            # Same host/path, standard port for each protocol, never a mirror change.
            host=target.hostname
            if ':' in host:host='['+host+']'
            url=urlunsplit((scheme,host,target.path,'',''))
            print('[Transport comparison] '+scheme+' exact failed path',flush=True)
            result=probe(image,[url,'8388608'],program=APT_PROBE)
            report['observations'].append({'scheme':scheme,'url':url,'result':result})
            save()
            check()
            if result.get('base_image_id')!=expected:
                report['status']='incomplete_identity_or_probe';return report
        def complete(row):
            result=row['result']
            return result.get('status')=='completed' and result.get('observation',{}).get('download_complete') is True
        first,second=map(complete,report['observations'])
        report['status']='compared'
        report['outcome']=('both_reachable' if first and second else 'https_only' if second else
                           'http_only' if first else 'neither_download_completed')
        if first and second:
            hashes=[r['result']['observation'].get('sha256') for r in report['observations']]
            report['same_content']=bool(hashes[0]) and hashes[0]==hashes[1]
    except Exception as error:
        report.update(status='comparison_error',error_type=type(error).__name__)
    finally:save()
    return report
