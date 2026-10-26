"""Describe matched-update data comparisons without selecting/promoting models."""
import json
from pathlib import Path

from compass.progress import atomic_json
from .scout_adapter_eval import summarize
from .scout_tokenizer import file_hash


def compare_observations(old_examples,new_examples,old_training,new_training,
                         old_common,new_common,old_transfer,new_transfer,updates):
    if not old_examples or new_examples[:len(old_examples)]!=old_examples or len(new_examples)<=len(old_examples):
        raise ValueError('Common examples must be an unchanged prefix with new approved rows')
    for training in (old_training,new_training):
        if training['status']!='passed' or len(training['steps'])!=updates:raise ValueError('Optimizer update count mismatch')
    for key in ('seed','lora','weights'):
        if old_training[key]!=new_training[key]:raise ValueError('Training control changed: '+key)
    for report in (old_common,new_common,old_transfer,new_transfer):
        if report['status']!='completed' or report.get('representation','locations')!='locations' or report.get('symbol_only',False):
            raise ValueError('Require complete original-interface evaluation')
        if report.get('task_control','issue_selection')!='issue_selection':raise ValueError('Lookup is not repair localization comparison')
        if report['generation']!=old_common['generation']:raise ValueError('Generation settings changed')
    if old_transfer['dataset_sha256']!=new_transfer['dataset_sha256']:raise ValueError('Transfer cohort changed')
    def check_rows(report,count):
        actual={(r['arm'],r['sample']) for r in report['rows']}
        expected={(arm,i) for arm in ('base','adapter') for i in range(count)}
        if len(actual)!=len(report['rows']) or actual!=expected:raise ValueError('Missing or repeated evaluation rows')
    check_rows(old_common,len(old_examples));check_rows(new_common,len(new_examples))
    transfer_count=len(old_transfer['rows'])//2
    if transfer_count<1:raise ValueError('Empty transfer cohort')
    check_rows(old_transfer,transfer_count);check_rows(new_transfer,transfer_count)
    common_rows=[r for r in new_common['rows'] if r['sample']<len(old_examples)]
    added_rows=[r for r in new_common['rows'] if r['sample']>=len(old_examples)]
    return {'status':'compared','optimizer_updates':updates,'production_promoted':False,'selected_checkpoint':None,
        'scope':'Exposed development teacher agreement, matched updates only; no independent repair or causal generalization claim',
        'common_controls':{'n':len(old_examples),'old':summarize(old_common['rows']),'new':summarize(common_rows)},
        'added_controls':{'n':len(new_examples)-len(old_examples),'new_only':summarize(added_rows),
            'scope':'Seen only by the new adapter; descriptive training fit, not transfer or an old/new comparison'},
        'transfer_controls':{'n':transfer_count,'old':summarize(old_transfer['rows']),'new':summarize(new_transfer['rows']),
            'scope':'Same exposed evaluation-only tasks; not independent heldout certification'},
        'training_cost':{name:{'updates':len(data['steps']),'epochs':data['epochs'],
            'input_token_positions':sum(s['input_tokens'] for s in data['steps']),
            'labelled_token_positions':sum(s['labelled_tokens'] for s in data['steps'])}
            for name,data in (('old',old_training),('new',new_training))},
        'limits':'Same update count does not imply equal tokens/FLOPs. Old examples have different repeat counts; one seed and no production promotion.'}


def compare_saved(protocol_path,output):
    protocol_path=Path(protocol_path);protocol=json.loads(protocol_path.read_text());inputs={str(protocol_path.resolve()):file_hash(protocol_path)}
    def load(path):
        path=Path(path);inputs[str(path.resolve())]=file_hash(path)
        return json.loads(path.read_text())
    pairs=[]
    for arm in ('old','new'):
        spec=protocol['comparison_inputs'][arm];dataset=Path(spec['dataset'])
        raw=(dataset/'development.jsonl').read_bytes();inputs[str((dataset/'development.jsonl').resolve())]=file_hash(dataset/'development.jsonl')
        examples=[json.loads(line) for line in raw.decode('utf-8').splitlines()]
        training_path=Path(spec['training_run'])/'training/training.json';training=load(training_path)
        parent=load(Path(spec['training_run'])/'report.json')
        if parent['status']!='passed' or parent['training_sha256']!=file_hash(training_path):raise ValueError('Training receipt drift')
        common=load(spec['common_report']);transfer=load(spec['transfer_report'])
        if common['dataset_sha256']!=file_hash(dataset/'development.jsonl') or training['dataset_sha256']!=common['dataset_sha256']:
            raise ValueError('Training/common dataset drift')
        for report in (common,transfer):
            if report['training_receipt_sha256']!=file_hash(training_path) or report['checkpoint_step']!=protocol['optimizer_updates']:
                raise ValueError('Evaluation refers to another training/checkpoint')
        pairs.append((examples,training,common,transfer,raw))
    old,new=pairs
    if not new[4].startswith(old[4]):raise ValueError('Original dataset bytes changed')
    result=compare_observations(old[0],new[0],old[1],new[1],old[2],new[2],old[3],new[3],protocol['optimizer_updates'])
    for path,expected in inputs.items():
        if file_hash(path)!=expected:raise ValueError('Comparison input changed')
    result['inputs']=inputs
    output=Path(output);output.mkdir(parents=True,exist_ok=False);atomic_json(output/'comparison.json',result)
    return result
