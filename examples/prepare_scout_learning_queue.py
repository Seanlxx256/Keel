"""Reconcile old candidate counts with later actual training and developer holds."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.scout_data_audit import _hash
from keel.scout_data_split import reconcile_learning_rows


def execute(reservation_path,review_path,export_path,assessments_path,output,*,timeout=60):
    started=time.monotonic()
    def check():
        if time.monotonic()-started>=timeout:raise TimeoutError('Learning queue deadline')
    paths=[Path(p).resolve() for p in (reservation_path,review_path,export_path,assessments_path)]
    inputs={str(p):_hash(p,check) for p in paths}
    reservation,review,exported,assessments=[json.loads(p.read_text(encoding='utf-8')) for p in paths]
    if (reservation['status']!='reserved_pending_review' or review['status']!='completed' or
        exported['status']!='exported_development_only'):raise ValueError('Completed development inputs required')
    if reservation['inputs'].get(str(paths[1]))!=inputs[str(paths[1])]:raise ValueError('Reservation review changed')
    data=paths[2].parent/'development.jsonl';inputs[str(data)]=_hash(data,check)
    if exported['dataset_sha256']!=inputs[str(data)]:raise ValueError('Actual training data changed')
    for path,expected in review['inputs'].items():
        if _hash(Path(path),check)!=expected:raise ValueError('Review evidence changed')
        inputs[path]=expected
    rows=reconcile_learning_rows(reservation,review,exported,assessments)
    for path,expected in inputs.items():
        if _hash(Path(path),check)!=expected:raise ValueError('Queue evidence changed before publication')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    result={'status':'reconciled_pending_review','inputs':inputs,'items':rows,'model_calls':0,'weight_updates':0,
        'counts':dict(Counter(r['reconciled_status'] for r in rows)),
        'new_training_approved':0,'ready_for_training':False,'independent_evaluation_eligible':False,
        'scope':'Metadata reconciliation of exposed cases, not semantic approval, new samples or training export',
        'seconds':round(time.monotonic()-started,3)}
    atomic_json(output/'queue.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('reservation','review','export','assessments','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=60);args=parser.parse_args()
    result=execute(args.reservation,args.review,args.export,args.assessments,args.output,timeout=args.timeout)
    print(json.dumps({'status':result['status'],'counts':result['counts'],'output':str(args.output/'queue.json')}))
