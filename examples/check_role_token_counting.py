"""Execute three frozen request interfaces with strict token counting."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.role_token_check import execute
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();report=execute(args.plan,resume=args.resume)
    print(json.dumps({'status':report['status'],'budget':report['budget'],'scope':report['scope']}))
