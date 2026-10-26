"""Prepare local base snapshots or collect bounded source-bound Scout responses."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_collection import prepare,collect,adopt_cohort_sources

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--prepared',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--adopt-cohort',type=Path)
    parser.add_argument('--prepare-timeout',type=float,default=180)
    parser.add_argument('--resume-from',type=Path)
    args=parser.parse_args()
    if not args.prepare_only and args.output is None:parser.error('--output required for collection')
    if args.adopt_cohort and not args.prepare_only:parser.error('--adopt-cohort requires --prepare-only')
    result=(adopt_cohort_sources(args.plan,args.adopt_cohort,args.prepared,timeout=args.prepare_timeout) if args.adopt_cohort
            else prepare(args.plan,args.prepared,timeout=args.prepare_timeout)) if args.prepare_only else collect(args.plan,args.prepared,args.output,resume_from=args.resume_from)
    print(json.dumps({k:result.get(k) for k in ('status','model_calls','budget','training_approved','scope')}))
    raise SystemExit(0 if result['status'] in ('prepared','collected_pending_review') else 1)
