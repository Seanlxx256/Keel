"""Configure Serena project metadata using its installed YAML dependency."""
import argparse
import hashlib
import json
from pathlib import Path


def update_config(data, language):
    if not isinstance(data,dict):
        raise ValueError('Serena project YAML must be a mapping')
    before=list(data.get('language_servers') or [])
    if not before:
        data['language_servers']=[language]
    # This integration is deliberately a read-only retrieval trial.
    data['read_only']=True
    return {'previous_language_servers':before,'language_servers':list(data['language_servers']),
            'read_only':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True,type=Path)
    parser.add_argument('--language-server',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    from ruamel.yaml import YAML
    from solidlsp.ls_config import LanguageServerRegistry
    language=LanguageServerRegistry.get_instance().resolve(args.language_server).get_key()
    project=args.project/'.serena/project.yml'
    if not project.is_file():
        raise ValueError('Create a Serena project first; missing .serena/project.yml')
    args.output.mkdir(parents=True,exist_ok=False)
    raw=project.read_bytes()
    (args.output/'project-before.yml').write_bytes(raw)
    yaml=YAML()
    data=yaml.load(raw.decode('utf-8'))
    result=update_config(data,language)
    with project.open('w',encoding='utf-8') as stream:
        yaml.dump(data,stream)
    result.update(status='configured',before_sha256=hashlib.sha256(raw).hexdigest(),
                  after_sha256=hashlib.sha256(project.read_bytes()).hexdigest())
    (args.output/'configuration.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':
    main()
