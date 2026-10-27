"""Explicit preparation/download/offline-training boundaries for Scout LoRA smoke."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_lora import download,train,PINS
from keel.scout_tokenizer import environment_receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','environment','download','train'])
    for name in ('output','dataset','tokenizer-run','torch-site','cache','weights','recover-from','reuse-preparation'):
        parser.add_argument('--'+name,type=Path,required=name=='output')
    parser.add_argument('--epochs',type=int,default=1)
    parser.add_argument('--max-updates',type=int)
    parser.add_argument('--reproducibility',choices=['legacy','strict'],default='legacy')
    parser.add_argument('--objective',choices=['generation','candidate_scores'],default='generation')
    parser.add_argument('--score-representation',default='legacy')
    parser.add_argument('--train-timeout',type=float,default=600)
    parser.add_argument('--environment-timeout',type=float,default=60)
    args=parser.parse_args()
    if args.action=='environment':
        started=time.monotonic()
        def phase(name):print(f'[LoRA environment +{time.monotonic()-started:.1f}s] {name}',flush=True)
        phase('dependency versions')
        from importlib import metadata
        for pin in PINS:
            name,version=pin.split('==')
            if metadata.version(name)!=version:raise ValueError('Training dependency pin mismatch')
        phase('import torch');import torch
        phase('CUDA availability')
        if torch.__version__!='2.5.1+cu121' or not torch.cuda.is_available():raise RuntimeError('Expected existing CUDA Torch unavailable')
        phase('import transformers model');from transformers import Qwen3ForCausalLM,AutoTokenizer
        phase('import peft');from peft import LoraConfig,get_peft_model
        phase('environment inventory');environment_receipt(args.output)
        phase('completed')
    elif args.action=='download':download(args.output,args.cache)
    elif args.action=='train':train(args.dataset,args.tokenizer_run,args.weights,args.output,epochs=args.epochs,max_updates=args.max_updates,reproducibility=args.reproducibility,objective=args.objective,score_representation=args.score_representation)
    else:
        from keel.scout_training_setup import prepare
        report=prepare(args.dataset,args.tokenizer_run,args.torch_site,args.output,recover_from=args.recover_from,
                       reuse_preparation=args.reuse_preparation,epochs=args.epochs,max_updates=args.max_updates,reproducibility=args.reproducibility,objective=args.objective,score_representation=args.score_representation,train_timeout=args.train_timeout,environment_timeout=args.environment_timeout)
        print(json.dumps({'status':report['status'],'report':str(args.output/'report.json')}))
