"""Append reviewed captured-source Scout examples without changing existing data."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_bound_export import export_bound

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('base-dataset','collection','review','reservation','output'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=60);args=parser.parse_args()
    result=export_bound(args.base_dataset,args.collection,args.review,args.reservation,args.output,timeout=args.timeout)
    print(json.dumps({k:result[k] for k in ('status','sample_count','tasks','model_calls','weight_updates')}))
