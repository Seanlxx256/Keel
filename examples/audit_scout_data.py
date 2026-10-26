"""Inventory possible Scout fine-tuning data without model calls or raw export."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_data_audit import audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path,action='append')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--timeout',type=int,default=120)
    args=parser.parse_args()
    report=audit(args.root,args.output,timeout=args.timeout)
    print(json.dumps({k:report.get(k) for k in ('status','discovered_transcripts','counts',
        'unique_candidates_by_task','training_approved','seconds')},indent=2))
    return 0 if report['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
