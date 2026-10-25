"""Measure registered request repacking on saved proposal transcripts; no provider."""
import argparse
from pathlib import Path
import sys
import json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.capacity_replay import replay

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transcript',type=Path,action='append',required=True)
    parser.add_argument('--policy',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    policy=json.loads(args.policy.read_text(encoding='utf-8')) if args.policy else None
    report=replay(args.transcript,args.output,policy=policy)
    print(json.dumps({k:report[k] for k in ('status','provider_calls','requests','changed_requests','saved_estimated_units')}))
