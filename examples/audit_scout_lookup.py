"""Replay saved lookup outputs without inference or training-label changes."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_lookup_audit import audit

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=60)
    args=parser.parse_args();report=audit(args.plan,args.output,timeout=args.timeout)
    print(json.dumps({'status':report['status'],'model_calls':0,'report':str(args.output/'report.json')}))
