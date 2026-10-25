"""Register, review, retire, and inspect bounded operational advice cards."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.operational_knowledge import OperationalKnowledge


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store',type=Path,required=True)
    sub=parser.add_subparsers(dest='action',required=True)
    register=sub.add_parser('register');register.add_argument('--card',type=Path,required=True)
    migrate=sub.add_parser('import-episodes');migrate.add_argument('--source',type=Path,required=True)
    for action in ('promote','deprecate'):
        command=sub.add_parser(action);command.add_argument('--id',required=True);command.add_argument('--revision',type=int,required=True)
    sub.add_parser('inspect')
    args=parser.parse_args();store=OperationalKnowledge(args.store.resolve())
    migration=None
    if args.action=='import-episodes':
        migration=store.import_episodes(args.source)
    elif args.action=='register':
        store.register(json.loads(args.card.read_text(encoding='utf-8')))
    elif args.action=='promote':
        store.promote(args.id,args.revision)
    elif args.action=='deprecate':
        store.deprecate(args.id,args.revision)
    rows=[{'id':i,'revision':r,'status':s,'sha256':h} for i,r,s,_,h in store.latest()]
    print(json.dumps({'catalog_sha256':store.catalog_hash(),'cards':rows,'migration':migration,'scope':'Explicitly reviewed operational advice; no automatic promotion from model claims.'}))


if __name__=='__main__':
    main()
