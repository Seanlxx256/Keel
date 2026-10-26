"""Audit a predeclared fixed-update Scout data comparison, without promotion."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_training_comparison import compare_saved

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--protocol',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=compare_saved(args.protocol,args.output)
    print(json.dumps({'status':report['status'],'production_promoted':False,'report':str(args.output/'comparison.json')}))
