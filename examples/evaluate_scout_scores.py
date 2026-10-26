"""Explicit fixed-threshold candidate-score evaluation."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_score_eval import evaluate_scores

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['dataset','tokenizer-run','training-run','output']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--evaluation-dataset',type=Path)
    parser.add_argument('--checkpoint-step',type=int)
    parser.add_argument('--candidate-permutation',default='original')
    parser.add_argument('--threshold',type=float,default=0.5)
    parser.add_argument('--max-items',type=int,default=8)
    args=parser.parse_args();report=evaluate_scores(**vars(args))
    print(json.dumps({'status':report['status'],'summary':report['summary']}))
