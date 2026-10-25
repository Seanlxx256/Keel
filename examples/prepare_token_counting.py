"""Prepare a hash-bound offline tokenizer and strict policy; no model API calls."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.tokenizer_setup import prepare,export_encoding,recover_encoding

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-config',type=Path,required=True)
    parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--transcript',type=Path,action='append',default=[])
    parser.add_argument('--recover-from',type=Path)
    parser.add_argument('--install',action='store_true',help='Explicitly install the token-counting extra into this interpreter environment')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.worker:
        if args.recover_from:recover_encoding(args.model_config,args.policy,args.recover_from,args.output)
        else:export_encoding(args.model_config,args.policy,args.output)
    else:
        report=prepare(args.model_config,args.policy,args.output,install=args.install,transcripts=args.transcript,recover_from=args.recover_from)
        print(json.dumps({'status':report['status'],'provider_calls':0,'policy':str(args.output/'policy.json')}))
