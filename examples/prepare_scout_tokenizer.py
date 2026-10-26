"""Prepare a dedicated tokenizer environment; no model weights or training."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_tokenizer_setup import prepare

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=600)
    parser.add_argument('--recover-from',type=Path)
    args=parser.parse_args()
    report=prepare(args.dataset,args.output,timeout=args.timeout,recover_from=args.recover_from)
    print(json.dumps({'status':report['status'],'model_calls':0,'weight_updates':0,'report':str(args.output/'report.json')}))
