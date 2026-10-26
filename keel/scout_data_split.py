"""Metadata-only, task-group-safe development data reservation; no label approval."""
from collections import Counter
import json
from pathlib import Path
import time
from compass.progress import atomic_json
from .scout_data_audit import _hash

PARTITIONS={'training_review','transfer_review','quarantine'}


def reconcile_learning_rows(reservation,review,exported,assessments):
    """Overlay later approvals/actual use without mutating a prior reservation.

    A queue is not a new approval. In particular, transfer tasks, previously used
    examples and explicit developer holds cannot become fresh training examples.
    """
    def indexed(items):
        result={}
        for item in items:
            key=item['sample_id']
            if key in result:raise ValueError('Duplicate learning-queue sample')
            result[key]=item
        return result
    reserved=indexed(reservation['items']);reviewed=indexed(review['items'])
    trained=indexed(exported['samples']);prior=indexed(assessments['items'])
    if reserved.keys()!=reviewed.keys() or not trained.keys()<=reserved.keys() or not prior.keys()<=reserved.keys():
        raise ValueError('Learning-queue inventory mismatch')
    result=[]
    for key,row in reserved.items():
        current=reviewed[key];decision=prior.get(key)
        if current['example_sha256']!=row['example_sha256'] or current['instance_id']!=row['instance_id']:
            raise ValueError('Learning-queue sample identity mismatch')
        if decision and decision.get('example_sha256')!=row['example_sha256']:
            raise ValueError('Prior assessment identity mismatch')
        if key in trained:
            if row['partition']!='training_review' or trained[key]['example_sha256']!=row['example_sha256']:
                raise ValueError('Previously trained sample outside training partition or changed')
            status='already_trained'
        elif row['partition']=='transfer_review':status='reserved_transfer_only'
        elif row['partition']=='quarantine':status='quarantined'
        elif row['partition']!='training_review':raise ValueError('Unknown learning partition')
        elif row['status']!='pending_semantic_review':status='blocked_by_existing_review'
        elif decision and decision['decision'].startswith('exclude_'):status='excluded_by_prior_assessment'
        elif decision and decision['decision'].startswith('hold_'):status='held_by_prior_assessment'
        else:status='needs_source_and_semantic_review'
        result.append({**row,'reconciled_status':status,'actual_previously_trained':key in trained,
            'new_training_approved':False,'prior_assessment':None if decision is None else {
                'decision':decision['decision'],'rationale':decision.get('rationale')},
            'next_action':{
                'already_trained':'Do not count as new task diversity',
                'reserved_transfer_only':'Preserve evaluation-only task boundary',
                'quarantined':'Resolve provenance and source-state evidence before label review',
                'blocked_by_existing_review':'Resolve the existing contract/provenance decision',
                'excluded_by_prior_assessment':'Preserve exclusion; no repeated training weight',
                'held_by_prior_assessment':'Establish source-level relevance before approval; do not rewrite teacher',
                'needs_source_and_semantic_review':'Read original goal, source and teacher before explicit developer review'}[status]})
    return result


def partition_rows(review,audit,trained,assignments):
    tasks={r['instance_id'] for r in review}
    if tasks!=set(assignments):raise ValueError('Explicit assignment required for every reviewed task, without extras')
    groups={}
    for task,assignment in assignments.items():
        if set(assignment)!={'group','partition'} or not isinstance(assignment['group'],str) or not assignment['group']:
            raise ValueError('Explicit nonempty task group required')
        group,partition=assignment['group'],assignment['partition']
        if partition not in PARTITIONS:raise ValueError('Unknown partition')
        if group in groups and groups[group]!=partition:raise ValueError('Task group crosses partitions')
        groups[group]=partition
    trained_tasks={r['instance_id'] for r in trained}
    if not trained_tasks<=tasks:raise ValueError('Previously trained task missing from reservation')
    if any(assignments[task]['partition']!='training_review' for task in trained_tasks):
        raise ValueError('Previously trained task cannot become transfer evaluation')
    used={r['example_sha256'] for r in trained}
    catalog={(r['transcript'],r['request_line'],r['response_line']):r for r in audit}
    result=[];seen_states={};seen_samples=set()
    for row in review:
        if row['sample_id'] in seen_samples:raise ValueError('Duplicate reviewed sample')
        seen_samples.add(row['sample_id'])
        original=catalog[(row['transcript'],row['request_line'],row['response_line'])]
        if original['example_sha256']!=row['example_sha256']:raise ValueError('Review/audit sample identity changed')
        assignment=assignments[row['instance_id']];partition=assignment['partition']
        state=original['state_sha256']
        if state in seen_states and seen_states[state]!=partition:raise ValueError('Same input state crosses partitions')
        seen_states[state]=partition
        status='pending_semantic_review' if row['decision']=='needs_semantic_review' else 'blocked_'+row['decision']
        result.append({'sample_id':row['sample_id'],'instance_id':row['instance_id'],**assignment,
            'example_sha256':row['example_sha256'],'state_sha256':state,'kind':row['kind'],
            'status':status,'previously_trained_control':row['example_sha256'] in used,
            'training_approved':False,'independent_evaluation_eligible':False})
    return result


def prepare(audit_dir,review_path,export_path,assignment_path,output,*,timeout=60):
    started=time.monotonic()
    def check():
        if time.monotonic()-started>=timeout:raise TimeoutError('Data reservation deadline')
    audit_dir,review_path,export_path,assignment_path,output=map(lambda p:Path(p).resolve(),
        (audit_dir,review_path,export_path,assignment_path,output))
    sources=[audit_dir/'report.json',audit_dir/'candidates.jsonl',review_path,export_path,assignment_path,
             export_path.parent/'development.jsonl']
    hashes={str(p):_hash(p,check) for p in sources}
    audit=json.loads(sources[0].read_text());review=json.loads(review_path.read_text())
    exported=json.loads(export_path.read_text());assignments=json.loads(assignment_path.read_text())
    if audit['status']!='completed' or review['status']!='completed' or exported['status']!='exported_development_only':
        raise ValueError('Completed audit/review and prior development export required')
    if exported['dataset_sha256']!=hashes[str(sources[-1])]:raise ValueError('Previously used dataset changed')
    if audit['candidates_sha256']!=hashes[str(sources[1])]:raise ValueError('Audit candidates changed')
    for name,identity in review['inputs'].items():
        if _hash(Path(name),check)!=identity:raise ValueError('Reviewed source evidence changed')
    candidates=[json.loads(line) for line in sources[1].read_text().splitlines()]
    rows=partition_rows(review['items'],candidates,exported['samples'],assignments['tasks'])
    for name,identity in hashes.items():
        if _hash(Path(name),check)!=identity:raise ValueError('Reservation input changed')
    output.mkdir(parents=True,exist_ok=False)
    report={'status':'reserved_pending_review','inputs':hashes,'model_calls':0,'weight_updates':0,
        'scope':'Explicit groups of already-exposed development tasks, not blind heldout or approved train/test data',
        'assignments':assignments,'items':rows,'counts':dict(Counter(r['status'] for r in rows)),
        'partition_counts':dict(Counter(r['partition'] for r in rows)),
        'ready_for_training':False,'ready_for_independent_evaluation':False,
        'seconds':round(time.monotonic()-started,3)}
    atomic_json(output/'reservation.json',report)
    return report
