"""Zero-model Docker check of BuildKit export -> official SDK builder import."""
import argparse
import json
from pathlib import Path
import shlex
import sys
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.apt_archive_bridge import export_archives,install_archive_policy,RESTORE_PROGRAM


def execute(diagnosis,script,output,*,timeout=600):
    import docker
    import swebench.harness.docker_build as builds
    if type(timeout) is not int or not 90<=timeout<=1200:raise ValueError('Check deadline90..1200seconds')
    output=Path(output);output.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    report={'status':'running','model_calls':0,'scope':'Actual archive transport and cleanup only; no APT installation, repair or official acceptance'}
    def remaining():
        value=timeout-(time.monotonic()-started)
        if value<=0:raise TimeoutError('Archive bridge selfcheck deadline')
        return value
    def save():atomic_json(output/'report.json',report)
    client=None;consumer='keel-apt-consumer:'+uuid.uuid4().hex
    save()
    try:
        exported=export_archives(diagnosis,script,output/'export',timeout=min(300,int(remaining())-30))
        report['export']=exported;save()
        if exported['status']!='completed':raise RuntimeError('Archive export failed: '+exported.get('error','see export receipt')+'; no download fallback')
        artifact=exported['artifact'];install_archive_policy(artifact)
        client=docker.from_env(timeout=max(1,int(remaining())))
        original=client.api.build
        def offline_build(*args,**kwargs):
            kwargs.update(network_mode='none',use_config_proxy=False)
            return original(*args,**kwargs)
        client.api.build=offline_build
        before='python -B -c '+shlex.quote(RESTORE_PROGRAM)+' before'
        after='python -B -c '+shlex.quote(RESTORE_PROGRAM)+' after'
        script_text='set -euxo pipefail\n# Keel APT archives transport selfcheck\n'+before+'\n'+after+'\n'
        dockerfile='FROM '+artifact['base_image']+"\nCOPY setup_repo.sh /root/\nRUN sed -i 's/\\r$//' /root/setup_repo.sh && /bin/bash /root/setup_repo.sh\n"
        context=output/'consumer';context.mkdir()
        print('[Archive bridge] official SDK builder import; network disabled; no package install',flush=True)
        builds.build_image(consumer,{'setup_repo.sh':script_text},dockerfile,'linux/amd64',client,context)
        remaining()
        observations=[]
        for line in (context/'build_image.log').read_text(encoding='utf-8',errors='replace').splitlines():
            if 'KEEL_APT_ARCHIVE_BRIDGE=' in line:
                try:observations.append(json.loads(line.split('KEEL_APT_ARCHIVE_BRIDGE=',1)[1]))
                except ValueError:pass
        if not observations or observations[-1].get('injected_files',0)<=0:
            raise ValueError('No actual imported archive observation')
        report.update(status='passed',import_observation=observations[-1])
    except Exception as error:
        report.update(status='unavailable',error_type=type(error).__name__,error=str(error)[:1000])
    finally:
        if client:
            try:client.images.remove(consumer,force=False)
            except Exception as error:report['consumer_cleanup_error']=type(error).__name__
            client.close()
        report['seconds']=round(time.monotonic()-started,3);save()
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--diagnosis',required=True,type=Path);p.add_argument('--apt-script',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--timeout',type=int,default=600)
    args=p.parse_args();value=execute(args.diagnosis,args.apt_script,args.output,timeout=args.timeout)
    print(json.dumps(value,indent=2));raise SystemExit(0 if value['status']=='passed' else 1)
