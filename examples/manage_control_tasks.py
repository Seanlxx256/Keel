"""Trusted controller-side queue administration, not a worker API."""
import argparse
import json
from pathlib import Path

from keel.control_service import ControlService


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--principal',required=True)
    parser.add_argument('--id',required=True)
    sub=parser.add_subparsers(dest='action',required=True)
    enqueue=sub.add_parser('enqueue');enqueue.add_argument('--payload',type=Path,required=True)
    sub.add_parser('status')
    requeue=sub.add_parser('requeue')
    requeue.add_argument('--fence',type=int,required=True)
    requeue.add_argument('--reason',required=True,help='Recorded decision after inspecting possible external effects')
    args=parser.parse_args()
    service=ControlService(json.loads(args.config.read_text(encoding='utf-8')))
    if args.principal not in service.principals:parser.error('Principal is not configured')
    grant=service.principals[args.principal]
    if args.action=='enqueue':
        result=service.queue.enqueue(args.id,args.principal,grant['task_id'],
                                     json.loads(args.payload.read_text(encoding='utf-8')))
    else:
        result=service.queue.status(args.principal,grant['task_id'],args.id)
        if args.action=='requeue':result=service.queue.requeue(args.id,args.fence,args.reason)
    print(json.dumps(result))


if __name__=='__main__':main()
