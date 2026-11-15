"""Inspect only a persisted acceptance job's labelled containers; no task replay."""
import argparse
import json
from pathlib import Path

from compass.progress import atomic_json
from keel.control_service import ControlService


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--principal',required=True);parser.add_argument('--run-id',required=True)
    parser.add_argument('--job-id',required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--remove',action='store_true')
    parser.add_argument('--quiesced',action='store_true',help='Acknowledge the original controller/worker has stopped')
    parser.add_argument('--max-seconds',type=float,default=10)
    args=parser.parse_args()
    if args.remove and not args.quiesced:parser.error('Removal requires explicit --quiesced acknowledgement')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:json.dump({'status':'started'},stream)
    try:
        service=ControlService(json.loads(args.config.read_text(encoding='utf-8')))
        broker=service.execution_broker
        if broker is None:raise ValueError('Execution broker not configured')
        principal=service.principals[args.principal]
        with service.store.transaction() as db:
            service._session(db,principal,args.run_id)
            row=db.execute('SELECT * FROM broker_verifications WHERE id=? AND principal=? AND run_id=?',
                           (args.job_id,args.principal,args.run_id)).fetchone()
            if row is None:raise ValueError('Job does not belong to the requested principal/run')
        print('[Execution cleanup] known identities only; no acceptance replay',flush=True)
        result=broker.containers.inspect_job(args.job_id,remove=args.remove,timeout=args.max_seconds)
        result['test_result_changed']=False
        result['operator_quiesced_acknowledged']=args.quiesced
        with service.store.transaction() as db:
            service.store._event(db,args.run_id,args.job_id,'operator_container_inspection',result)
        atomic_json(args.output,result);print(json.dumps(result))
        return 0 if not args.remove or result['confirmed_absent'] else 1
    except Exception as error:
        atomic_json(args.output,{'status':'unavailable','error_type':type(error).__name__})
        raise


if __name__=='__main__':raise SystemExit(main())
