"""Isolated preparation child; tokenizer download and offline checking separated."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_tokenizer import environment_receipt,download_assets,check_dataset


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['environment','download','check'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--assets',type=Path)
    parser.add_argument('--cache',type=Path)
    parser.add_argument('--dataset',type=Path)
    args=parser.parse_args()
    if args.action=='environment':environment_receipt(args.output)
    elif args.action=='download':download_assets(args.assets,args.cache)
    else:check_dataset(args.dataset,args.assets,args.output)


if __name__=='__main__':main()
