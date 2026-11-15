"""Trusted local write adjudication; never exposed as a worker RPC."""
import argparse
import json
from pathlib import Path

from compass.progress import atomic_json
from keel.control_service import ControlService


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='New receipt file; existing evidence is preserved')
    commands=parser.add_subparsers(dest='action',required=True)
    preview=commands.add_parser('preview')
    preview.add_argument('--principal',required=True);preview.add_argument('--run-id',required=True)
    preview.add_argument('--operation-id',required=True)
    resolve=commands.add_parser('resolve')
    resolve.add_argument('--plan',type=Path,required=True)
    resolve.add_argument('--decision',choices=['applied','no_effect'],required=True)
    resolve.add_argument('--operator',required=True);resolve.add_argument('--reason',required=True)
    resolve.add_argument('--quiesced',action='store_true',help='Acknowledge original worker/effects have been stopped and inspected')
    args=parser.parse_args()
    if args.action=='resolve' and not args.quiesced:parser.error('Resolution requires explicit --quiesced acknowledgement')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump({'status':'started','action':args.action},stream)
    try:
        print('[Write adjudication] '+args.action+'; no source write or task replay',flush=True)
        service=ControlService(json.loads(args.config.read_text(encoding='utf-8')))
        if service.write_broker is None:raise ValueError('Controller has no write broker')
        if args.action=='preview':
            value=service.write_broker.resolution_plan(args.principal,args.run_id,args.operation_id)
            # This file itself is the plan accepted by resolve, without summary loss.
            atomic_json(args.output,value)
            print(json.dumps({'status':'observed','plan':str(args.output),'automatic_decision':False}))
        else:
            value=service.write_broker.resolve(json.loads(args.plan.read_text(encoding='utf-8')),
                decision=args.decision,operator=args.operator,reason=args.reason,quiesced=args.quiesced)
            atomic_json(args.output,value)
            print(json.dumps(value))
    except Exception as error:
        atomic_json(args.output,{'status':'failed','action':args.action,'error_type':type(error).__name__,'message':str(error)})
        raise


if __name__=='__main__':main()
