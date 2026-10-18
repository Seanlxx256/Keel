"""Install Serena separately, record its version, then discover real MCP contracts."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def launch_config(root, python, executable, help_text):
    args=['start-mcp-server','--transport','stdio','--project',str(root)]
    if '--agent-interface' in help_text:
        args+=['--agent-interface','tools']
    for flag in ('--enable-web-dashboard','--open-web-dashboard','--enable-gui-log-window'):
        if flag in help_text:
            args += [flag,'false']
    # This launcher only supplies a documented data directory and invokes Serena.
    home=root/'.keel/tools/serena-home'
    launcher=root/'.keel/tools/launch-serena.py'
    launcher.parent.mkdir(parents=True,exist_ok=True)
    launcher.write_text('import os\n'+f"os.environ['SERENA_HOME'] = {str(home)!r}\n"+
        f'os.execv({str(executable)!r}, {([str(executable)]+args)!r})\n',encoding='utf-8')
    return {'serena':{'command':str(python),'args':[str(launcher)],'timeout':120,'tools':{}}}


def setup(root,output,version=None,install=True,discover=True,language_server=None):
    if version and not re.fullmatch(r'[0-9][A-Za-z0-9.]*',version):
        raise ValueError('Version must be an exact release version')
    output.mkdir(parents=True,exist_ok=False)
    report={'status':'preparing','model_calls':0,'tools_authorized':0}
    env={**os.environ,'UV_CACHE_DIR':str(root/'.keel/tools/uv-cache'),
         'UV_PYTHON_INSTALL_DIR':str(root/'.keel/tools/python'),'UV_HTTP_RETRIES':'0',
         'SERENA_HOME':str(root/'.keel/tools/serena-home')}
    uv=shutil.which('uv')
    target=root/'.keel/tools/serena-venv'
    bin_dir=target/('Scripts' if os.name=='nt' else 'bin')
    python=bin_dir/('python.exe' if os.name=='nt' else 'python')
    executable=bin_dir/('serena.exe' if os.name=='nt' else 'serena')
    def command(argv,log,timeout=600):
        print('[Serena setup] '+log,flush=True)
        with (output/log).open('wb') as stream:
            result=subprocess.run(argv,env=env,cwd=root,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
        if result.returncode:
            raise RuntimeError('Command failed; inspect '+str(output/log))
    try:
        if install:
            if not uv:
                raise ValueError('uv is required; install uv first or use --no-install with an existing Serena environment')
            if not python.is_file():
                command([uv,'venv','--python',sys.executable,str(target)],'venv.log',60)
            installed=subprocess.run([str(python),'-c',"import importlib.metadata; print(importlib.metadata.version('serena-agent'))"],
                capture_output=True,text=True,timeout=30)
            if installed.returncode or (version and installed.stdout.strip()!=version):
                package='serena-agent'+('=='+version if version else '')
                command([uv,'pip','install','--python',str(python),package],'install.log')
        if not python.is_file() or not executable.is_file():
            raise ValueError('Serena is not installed in the isolated environment')
        versions=subprocess.run([str(python),'-c',"import importlib.metadata as m,json; print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))"],
            check=True,capture_output=True,text=True,timeout=30)
        inventory=json.loads(versions.stdout)
        (output/'installed-versions.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
        report['serena_version']=next((v for k,v in inventory.items() if k.lower().replace('_','-')=='serena-agent'),None)
        help_result=subprocess.run([str(executable),'start-mcp-server','--help'],env=env,capture_output=True,text=True,
            encoding='utf-8',errors='replace',timeout=45,check=True)
        (output/'server-help.txt').write_text(help_result.stdout,encoding='utf-8')
        if language_server is None and (root/'pyproject.toml').is_file():
            tracked=subprocess.run(['git','-c','safe.directory='+str(root),'-C',str(root),'ls-files','--','*.py'],
                capture_output=True,text=True,timeout=15)
            if tracked.returncode==0 and tracked.stdout.strip():
                language_server='python'
        if language_server:
            if not (root/'.serena/project.yml').is_file():
                command([str(executable),'project','create',str(root),'--language',language_server],
                        'project-create.log',120)
            command([str(python),str(root/'examples/configure_serena_project.py'),'--project',str(root),
                '--language-server',language_server,'--output',str(output/'project-config')],'project-config.log',45)
            report['project_configuration']='read-only; language-server list checked'
        config=launch_config(root,python,executable,help_result.stdout)
        config_path=output/'discovery-config.json'
        config_path.write_text(json.dumps(config,indent=2),encoding='utf-8')
        report.update(status='installed_discovery_pending',config=str(config_path))
        if discover:
            command([sys.executable,str(root/'examples/check_external_tool.py'),'--config',str(config_path),
                '--repo',str(root),'--discover-server','serena','--output',str(output/'discovery')],'discovery.log',150)
            result=json.loads((output/'discovery/check.json').read_text(encoding='utf-8'))
            report.update(status='discovered',tools_discovered=result['tools_discovered'])
    except Exception as error:
        report.update(status='setup_incomplete',error_type=type(error).__name__)
        if isinstance(error,(ValueError,RuntimeError)):
            report['diagnostic']=str(error)
    finally:
        (output/'setup.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--version')
    parser.add_argument('--no-install',action='store_true')
    parser.add_argument('--no-discover',action='store_true')
    parser.add_argument('--language-server')
    args=parser.parse_args()
    result=setup(Path(__file__).resolve().parents[1],args.output.resolve(),args.version,
                 install=not args.no_install,discover=not args.no_discover,language_server=args.language_server)
    print(json.dumps(result,indent=2))
    return 0 if result['status'] in ('discovered','installed_discovery_pending') else 1


if __name__=='__main__':
    raise SystemExit(main())
