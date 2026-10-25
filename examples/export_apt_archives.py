"""Export an existing diagnostic APT cache; never install or download packages."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.apt_archive_bridge import export_archives


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnosis',required=True,type=Path)
    parser.add_argument('--apt-script',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--timeout',type=int,default=300)
    args=parser.parse_args()
    result=export_archives(args.diagnosis,args.apt_script,args.output,timeout=args.timeout)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
