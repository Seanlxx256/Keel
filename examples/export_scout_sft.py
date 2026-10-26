"""Export explicitly reviewed Scout controls; no model download or training."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_sft import export_development


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=120)
    args=parser.parse_args()
    result=export_development(args.review,args.output,timeout=args.timeout)
    print(json.dumps({k:result.get(k) for k in ('status','sample_count','tasks','weight_updates',
        'target_tokenizer_validation','seconds')}))
    return 0 if result['status']=='exported_development_only' else 1


if __name__=='__main__':raise SystemExit(main())
