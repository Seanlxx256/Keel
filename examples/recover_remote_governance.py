"""Inspect an interrupted remote control session; never replay external actions."""
import argparse
import json
from pathlib import Path

from keel.remote_governance import RemoteSession


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True,
                        help='Remote governance object, or task JSON containing governance')
    parser.add_argument('--reconcile',action='store_true',help='Reconcile exactly the saved pending RPC')
    parser.add_argument('--close-failed',action='store_true',help='Close the interrupted run as failed')
    args=parser.parse_args()
    config=json.loads(args.config.read_text(encoding='utf-8'))
    session=RemoteSession.recover(config.get('governance',config))
    if session.pending is not None:
        if not args.reconcile:
            print(json.dumps({'status':'reconciliation_required','run_id':session.run_id,
                              'action':session.pending['action'],'external_actions_replayed':0}))
            return 2
        session.reconcile_pending()
    report=session.report()
    if args.close_failed:
        session.finish('failed')
        report=session.report()
    print(json.dumps({'status':'inspected','run_id':session.run_id,'report':report,
                      'recovery_only':True,'external_actions_replayed':0}))
    return 0


if __name__=='__main__':raise SystemExit(main())
