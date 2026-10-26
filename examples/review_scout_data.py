"""Review queued Scout examples offline; never approve or export training targets."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_data_review import review


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--queue',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=120)
    args=parser.parse_args()
    result=review(args.audit,args.queue,args.output,timeout=args.timeout)
    print(json.dumps({k:result.get(k) for k in ('status','counts','training_approved','model_calls','seconds')}))
    return 0 if result['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
