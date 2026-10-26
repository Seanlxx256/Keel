"""Reserve development data by task group before further training or tuning."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_data_split import prepare

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('audit','review','export','assignments','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=prepare(args.audit,args.review,args.export,args.assignments,args.output)
    print(json.dumps({key:result[key] for key in ('status','counts','partition_counts','ready_for_training')}))
