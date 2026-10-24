"""Compare HTTP/HTTPS acquisition for one recorded failed URL without model calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.network_transport_comparison import compare_transports


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--failed-workload',type=Path,required=True)
    parser.add_argument('--apt-script',type=Path,required=True)
    parser.add_argument('--image',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--url-index',type=int,default=0)
    parser.add_argument('--timeout',type=int,default=200)
    args=parser.parse_args()
    result=compare_transports(args.failed_workload.resolve(),args.apt_script.resolve(),args.image,
                              args.output.resolve(),timeout=args.timeout,url_index=args.url_index)
    print(json.dumps(result))
    return 0 if result['status']=='compared' else 1


if __name__=='__main__':raise SystemExit(main())
