"""Zero-model local-image build check; no repositories, package downloads or network settings."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from examples.swebench_bridge import run_harness


def check(image,output,timeout=60):
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]*',image) or image.startswith('sha256:'):
        raise ValueError('Require named local image')
    if type(timeout) is not int or not 5<=timeout<=120:
        raise ValueError('Build timeout must be5..120seconds')
    output.mkdir(parents=True,exist_ok=False)
    report={'status':'checking','model_calls':0,'image':image,
            'scope':'Local-image FROM plus Python print with build network disabled; not APT, model or reference recovery'}
    def save():(output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    tag='keel-runtime-check:'+uuid.uuid4().hex
    save()
    try:
        for name,command in [('info',['docker','info','--format','{{json .ServerVersion}}']),
                             ('inspect',['docker','image','inspect','--format','{{.Id}}',image])]:
            report['stage']=name;save()
            directory=output/name;directory.mkdir()
            result=run_harness(command,cwd=directory,log_path=directory/'command.log',timeout=10)
            if result.returncode!=0:
                report.update(status='unavailable',stage=name,returncode=result.returncode)
                return report
        report['base_image_id']=(output/'inspect/command.log').read_text(encoding='utf-8').strip()
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',report['base_image_id']):
            raise ValueError('Invalid image identity response')
        context=output/'context';context.mkdir()
        command=json.dumps(['python','-c',"print('KEEL_DOCKER_RUNTIME_READY')"])
        (context/'Dockerfile').write_text('FROM '+image+'\nRUN '+command+'\n',encoding='utf-8',newline='\n')
        directory=output/'build';directory.mkdir()
        report.update(status='building',stage='build');save()
        result=run_harness(['docker','build','--pull=false','--no-cache','--network=none','--progress=plain','-t',tag,str(context.resolve())],cwd=directory,log_path=directory/'build.log',timeout=timeout)
        report.update(status='passed' if result.returncode==0 else 'failed',returncode=result.returncode)
        if result.returncode==0:
            directory=output/'inspect-after';directory.mkdir()
            after=run_harness(['docker','image','inspect','--format','{{.Id}}',image],cwd=directory,log_path=directory/'command.log',timeout=10)
            if after.returncode!=0 or (directory/'command.log').read_text(encoding='utf-8').strip()!=report['base_image_id']:
                report['status']='base_identity_changed'

    except subprocess.TimeoutExpired:
        report.update(status='timed_out')
    except Exception as error:
        report.update(status='unavailable',error_type=type(error).__name__)
    finally:
        save()
        cleanup=output/'cleanup';cleanup.mkdir()
        try:
            result=run_harness(['docker','image','rm',tag],cwd=cleanup,log_path=cleanup/'command.log',timeout=5)
            report['cleanup_returncode']=result.returncode
        except Exception as error:report['cleanup_error_type']=type(error).__name__
        report['cleanup_scope']='Only unique selfcheck image tag; Docker daemon-side cancellation not independently certified'
        save()
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--timeout',type=int,default=60)
    args=parser.parse_args()
    result=check(args.image,args.output.resolve(),args.timeout)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
