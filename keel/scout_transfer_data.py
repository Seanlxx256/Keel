"""Export reviewed exposed-transfer controls through an evaluation-only gate."""
import json
from pathlib import Path
import time
from compass.progress import atomic_json
from .scout_tokenizer import file_hash
from .scout_data_review import load_event_pair,inspect_selection
from .scout_data_audit import _selection
from .scout_sft import training_prompt,_base_source


def check_transfer_scope(case,reservation,training_tasks):
    if case['instance_id'] in training_tasks:raise ValueError('Task already present in training data')
    row=next(r for r in reservation['items'] if r['sample_id']==case['sample_id'])
    if row['instance_id']!=case['instance_id']:raise ValueError('Transfer sample/task mismatch')
    if row['partition']!='transfer_review' or row['previously_trained_control']:
        raise ValueError('Sample not reserved for transfer')
    trained_groups={r['group'] for r in reservation['items'] if r['instance_id'] in training_tasks}
    if row['group'] in trained_groups:raise ValueError('Transfer group overlaps training')
    if (case['decision']!='approved_development_transfer' or case['use']!='evaluation_only' or
        case['independent_evaluation_eligible'] is not False or case['raw_target_modified'] is not False):
        raise ValueError('Transfer approval scope changed')


def export(review_path,reservation_path,training_export,approvals_path,output):
    started=time.monotonic()
    def remaining():
        value=60-(time.monotonic()-started)
        if value<=0:raise TimeoutError('Transfer export deadline')
        return value
    review_path,reservation_path,training_export,approvals_path,output=map(Path,
        (review_path,reservation_path,training_export,approvals_path,output))
    paths=[review_path,reservation_path,training_export,approvals_path,training_export.parent/'development.jsonl']
    hashes={str(p.resolve()):file_hash(p) for p in paths}
    review=json.loads(review_path.read_text());reservation=json.loads(reservation_path.read_text())
    training=json.loads(training_export.read_text());approved=json.loads(approvals_path.read_text())
    if (approved['review_sha256']!=file_hash(review_path) or approved['reservation_sha256']!=file_hash(reservation_path)
        or training['dataset_sha256']!=file_hash(paths[-1])):raise ValueError('Transfer source identity changed')
    byid={r['sample_id']:r for r in review['items']};data=[];samples=[];tasks=set()
    for case in approved['items']:
        remaining()
        if case['decision']!='approved_development_transfer':continue
        check_transfer_scope(case,reservation,set(training['tasks']))
        if case['instance_id'] in tasks:raise ValueError('One representative per transfer task required')
        tasks.add(case['instance_id']);row=byid[case['sample_id']]
        if row['stage'] not in ('file_selection','symbol_selection'):raise ValueError('Page action is not final localization')
        request,response=load_event_pair(row['transcript'],row['request_line'],row['response_line'],2097152,remaining)
        if _selection(request,response)['example_sha256']!=row['example_sha256']:raise ValueError('Teacher example changed')
        if inspect_selection(request,response,{})['decision']!='needs_semantic_review':raise ValueError('Current contract failed')
        messages=request['args'][0];payload=json.loads(messages[-1]['content'])
        receipt_path=Path(case['input_receipt']['path']);receipt=json.loads(receipt_path.read_text())
        if file_hash(receipt_path)!=case['input_receipt']['sha256'] or payload['goal']!=receipt['goal']:
            raise ValueError('Transfer original goal changed')
        if not case.get('source_evidence') or not case.get('rationale'):raise ValueError('Source-backed judgment required')
        for evidence in case['source_evidence']:
            if (evidence['receipt_sha256']!=file_hash(receipt_path) or evidence['base_commit']!=receipt['base_commit']):
                raise ValueError('Source receipt/base mismatch')
            _base_source(evidence,remaining)
        data.append({'prompt':training_prompt(messages,request['kwargs']['schema']),
                     'completion':[{'role':'assistant','content':response['content']}]})
        samples.append({'sample_id':case['sample_id'],'instance_id':case['instance_id'],'kind':row['kind'],
                        'example_sha256':row['example_sha256'],'use':'evaluation_only'})
    if not data:raise ValueError('No approved transfer controls')
    for name,identity in hashes.items():
        if file_hash(name)!=identity:raise ValueError('Transfer input changed')
    output.mkdir(parents=True,exist_ok=False)
    with (output/'evaluation.jsonl').open('x',encoding='utf-8',newline='\n') as stream:
        for example in data:stream.write(json.dumps(example,ensure_ascii=False)+'\n')
    report={'status':'exported_development_transfer_only','inputs':hashes,'samples':samples,
        'sample_count':len(samples),'dataset_sha256':file_hash(output/'evaluation.jsonl'),
        'training_allowed':False,'independent_evaluation_eligible':False,
        'scope':'Previously exposed public tasks, source-reviewed teacher agreement only; not blind heldout',
        'model_calls':0,'weight_updates':0}
    atomic_json(output/'export.json',report);return report
