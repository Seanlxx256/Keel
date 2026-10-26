"""Explicit preparation/download/offline-training boundaries for Scout LoRA smoke."""
import argparse
import json
import os
from pathlib import Path
import sys
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
    args=parser.parse_args()
    if args.action=='environment':
        from importlib import metadata
        for pin in PINS:
            name,version=pin.split('==')
            if metadata.version(name)!=version:raise ValueError('Training dependency pin mismatch')
        import torch
        if torch.__version__!='2.5.1+cu121' or not torch.cuda.is_available():raise RuntimeError('Expected existing CUDA Torch unavailable')
        from transformers import Qwen3ForCausalLM,AutoTokenizer
        from peft import LoraConfig,get_peft_model
        environment_receipt(args.output)
    elif args.action=='download':download(args.output,args.cache)
    elif args.action=='train':train(args.dataset,args.tokenizer_run,args.weights,args.output,epochs=args.epochs,max_updates=args.max_updates,reproducibility=args.reproducibility,objective=args.objective)
    else:
        from keel.scout_training_setup import prepare
        report=prepare(args.dataset,args.tokenizer_run,args.torch_site,args.output,recover_from=args.recover_from,
                       reuse_preparation=args.reuse_preparation,epochs=args.epochs,max_updates=args.max_updates,reproducibility=args.reproducibility,objective=args.objective)
        print(json.dumps({'status':report['status'],'report':str(args.output/'report.json')}))
