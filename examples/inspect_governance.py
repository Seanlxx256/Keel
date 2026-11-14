"""Trusted local operator CLI. No model, network, Docker or automatic replay."""
import argparse
import json
from pathlib import Path
import sqlite3

from keel.governance import ControlStore
from keel.core import PolicyDenied


def inspect(path, *, scope, run_id=None, after=0, limit=100, reconcile=False):
    path=Path(path).resolve(strict=True)
    store=ControlStore(path,initialize=False)
    if reconcile:
        expired=store.reconcile_expired(scope=scope)
    else:
        expired=[]
    result=store.inspect(scope=scope,run_id=run_id,after=after,limit=limit)
    result['expired_runs_marked']=expired
    result['scope_note']='Trusted local operator inspection, not an authenticated remote control endpoint.'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--scope',required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--after',type=int,default=0)
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--reconcile-expired',action='store_true',help='Mark expired runs unreachable; never retry/replay')
    args=parser.parse_args()
    try:
        result=inspect(args.db,scope=args.scope,run_id=args.run_id,after=args.after,
                       limit=args.limit,reconcile=args.reconcile_expired)
    except (ValueError,OSError,KeyError,sqlite3.Error,PolicyDenied) as error:
        parser.exit(2,f'Governance inspection unavailable: {error}\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
