"""Continue a failed frozen reference through registered recovery stages."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.reference_pipeline import recover_pipeline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('task','export','failed-grade','output'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--recipe-grade',type=Path)
    parser.add_argument('--timeout',type=int,default=1800)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--apt-archives',type=Path,help='Reuse existing workload-bound archive artifact; no export or download fallback')
    parser.add_argument('--instance-cache-scope',help='Explicit recipe-scoped build reuse; fresh test execution remains required')
    parser.add_argument('--preparation-root',type=Path,action='append',help='Discover assets in an authorized evidence directory and direct children; no recursive workspace scan')
    args=parser.parse_args()
    docker=Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH']=str(docker)+os.pathsep+os.environ.get('PATH','')
    result=recover_pipeline(args.task,args.export,args.failed_grade,args.output,
        python=sys.executable,timeout=args.timeout,recipe_grade=args.recipe_grade,resume=args.resume,
        apt_archives=args.apt_archives,instance_cache_scope=args.instance_cache_scope,
        preparation_roots=args.preparation_root)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='reference_verified' else 1


if __name__=='__main__':
    raise SystemExit(main())
