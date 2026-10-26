"""Export fixed local base sources; preserve unavailable tasks without scoring."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compass.preparation import prepare_archive_snapshot,check_archive_snapshot
from compass.progress import atomic_json
from keel.scout_tokenizer import file_hash


def execute(plan_path,output,timeout=300):
    plan_path,output=Path(plan_path),Path(output)
    plan=json.loads(plan_path.read_text());started=time.monotonic()
    def remaining():
        value=timeout-(time.monotonic()-started)
        if value<=0:raise TimeoutError('Source preparation deadline')
        return value
    for path,sha in plan['inputs'].items():
        if file_hash(path)!=sha:raise ValueError('Source plan input changed')
    inventory=json.loads(Path(plan['inventory']).read_text())
    if inventory['status']!='reserved_pending_source_export':raise ValueError('Completed fixed reservation required')
    selected=[r for r in inventory['rows'] if not r['previously_trained'] and r['partition']!='quarantine']
    output.mkdir(parents=True,exist_ok=False)
    report={'status':'preparing','plan_sha256':file_hash(plan_path),'rows':[],
            'model_calls':0,'weight_updates':0,'training_approved':False,
            'scope':'Pinned source exports only; unavailable tasks retained, no quality score or labels'}
    atomic_json(output/'report.json',report)
    try:
        for i,row in enumerate(selected):
            remaining();print(f"[Scout sources] {i+1}/{len(selected)} {row['instance_id']}",flush=True)
            current={**row,'source_export_verified':False}
            if row['source_status']!='commit_available':current['preparation_status']='source_unavailable'
            elif row['instance_id'] in plan.get('known_source_blocks',{}):
                block=plan['known_source_blocks'][row['instance_id']]
                if (block['base_commit']!=row['base_commit'] or block['source_repository']!=row['source_repository'] or
                    file_hash(block['archive'])!=block['archive_sha256']):raise ValueError('Prior source-block evidence changed')
                current.update(preparation_status='source_export_blocked',prior_block=block)
            else:
                reuse=plan.get('reuse_sources',{}).get(row['instance_id'])
                destination=Path(reuse) if reuse else output/row['instance_id']/'repo'
                try:
                    if reuse:
                        receipt=check_archive_snapshot(destination,row['base_commit'])
                        if receipt['repository_id']!=row['repo']:raise ValueError('Reuse repository mismatch')
                    else:
                        prepare_archive_snapshot(row['repo'],row['base_commit'],destination,
                            source=row['source_repository'],timeout=remaining())
                        receipt=check_archive_snapshot(destination,row['base_commit'])
                    current.update(preparation_status='reused_verified' if reuse else 'exported_verified',
                        source_export_verified=True,prepared_source=str(destination.resolve()),source_file_count=len(receipt['files']),
                        receipt_sha256=file_hash(destination.with_name(destination.name+'.export.json')))
                except TimeoutError:raise
                except (ValueError,OSError) as error:
                    if reuse:raise
                    current.update(preparation_status='source_export_blocked',error_type=type(error).__name__,
                        error=str(error)[:300],artifact_directory=str(destination.parent.resolve()))
            report['rows'].append(current);atomic_json(output/'report.json',report)
        for path,sha in plan['inputs'].items():
            remaining()
            if file_hash(path)!=sha:raise ValueError('Source plan changed during preparation')
        report.update(status='prepared_with_unavailable_sources',counts=dict(Counter(r['preparation_status'] for r in report['rows'])))
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__);raise
    finally:
        report['seconds']=round(time.monotonic()-started,3);atomic_json(output/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=300)
    args=parser.parse_args();report=execute(args.plan,args.output,args.timeout)
    print(json.dumps({k:report[k] for k in ('status','counts','model_calls')}))
