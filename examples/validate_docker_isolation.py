"""Run real Docker checks; unavailable Docker never becomes a local fallback."""
import argparse
import json
from pathlib import Path

from keel.docker_isolation import execute


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--image',help='Existing local image; omitted: inspect at most eight local images')
    parser.add_argument('--python',help='Python executable inside image')
    parser.add_argument('--max-seconds',type=float,default=240)
    parser.add_argument('--resume',action='store_true',help='New attempt with identical manifest; preserve earlier artifacts')
    args=parser.parse_args()
    report=execute(args.output,image=args.image,python=args.python,max_seconds=args.max_seconds,resume=args.resume)
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['status'] in {'passed','reused'} else 1


if __name__=='__main__':raise SystemExit(main())
