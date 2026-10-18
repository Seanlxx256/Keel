"""Create a role allowlist from discovered schemas and explicit operator selections."""
import argparse
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.mcp_client import validate_servers
from keel.evaluation_protocol import file_hash


def configure(connection,discovered,server,selected,*,roles,read_only):
    if server not in connection or not selected or len(selected)!=len(set(selected)):
        raise ValueError('Choose a configured server and unique explicit tool names')
    entries=discovered.get('tools',[])
    names=[row['name'] for row in entries]
    if len(names)!=len(set(names)) or not set(selected)<=set(names):
        raise ValueError('Selected tools must exist uniquely in the discovered catalog')
    config={server:copy.deepcopy(connection[server])}
    config[server]['tools']={}
    for name in selected:
        row=next(row for row in entries if row['name']==name)
        config[server]['tools'][name]={'roles':list(roles),'read_only':read_only,
            'description':'Operator-selected '+('read-only ' if read_only else '')+'tool '+name+'; use the supplied input schema.',
            'input_schema':row['input_schema']}
    validate_servers(config)
    return config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection',type=Path,required=True)
    parser.add_argument('--discovery',type=Path,required=True)
    parser.add_argument('--server',required=True)
    parser.add_argument('--tool',action='append',required=True)
    parser.add_argument('--role',action='append',choices=['scout','planner','implementer'],required=True)
    parser.add_argument('--read-only',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    config=configure(json.loads(args.connection.read_text(encoding='utf-8')),
        json.loads(args.discovery.read_text(encoding='utf-8')),args.server,args.tool,roles=args.role,read_only=args.read_only)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(config,stream,indent=2)
    receipt={'connection_sha256':file_hash(args.connection),'discovery_sha256':file_hash(args.discovery),
        'config_sha256':file_hash(args.output),'selected_tools':args.tool,'roles':args.role,
        'scope':'Explicit operator authorization; read-only is a declaration, not OS enforcement'}
    args.output.with_suffix('.receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({'status':'configured','tools_authorized':len(args.tool),'output':str(args.output)}))


if __name__=='__main__':
    main()
