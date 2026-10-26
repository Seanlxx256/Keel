"""Run paired exposed-development adapter evaluation without retraining."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_adapter_eval import evaluate

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','tokenizer-run','training-run','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--evaluation-dataset',type=Path)
    parser.add_argument('--checkpoint-step',type=int)
    parser.add_argument('--reuse-base-from',type=Path)
    parser.add_argument('--representation',choices=['locations','candidate_ids'],default='locations')
    parser.add_argument('--symbol-only',action='store_true')
    parser.add_argument('--candidate-permutation',default='original',help='original, reverse_ids, reverse_catalog, shuffle_ids:SEED or shuffle_catalog:SEED')
    parser.add_argument('--lookup-control',action='store_true')
    parser.add_argument('--lookup-presentation',choices=['original','without_goal','flat'],default='original')
    args=parser.parse_args()
    report=evaluate(args.dataset,args.tokenizer_run,args.training_run,args.output,evaluation_dataset=args.evaluation_dataset,
                    checkpoint_step=args.checkpoint_step,reuse_base_from=args.reuse_base_from,
                    representation=args.representation,symbol_only=args.symbol_only,lookup_control=args.lookup_control,
                    lookup_presentation=args.lookup_presentation,candidate_permutation=args.candidate_permutation)
    print(json.dumps({'status':report['status'],'summary':report['summary'],'report':str(args.output/'report.json')}))
