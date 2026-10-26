"""Target-independent presentation augmentation of approved symbol training rows."""
import json
from pathlib import Path
from compass.progress import atomic_json
from .scout_tokenizer import file_hash
from .scout_candidate_ids import numbered_example,permutation_mode


def rebuild(source,modes):
    from .scout_id_training import original_examples
    source=Path(source)
    meta=json.loads((source/'export.json').read_text())
    if meta['representation'] not in ('mixed_files_candidate_ids','subset_candidate_ids'):
        raise ValueError('Require plain ID or exact subset source')
    if not isinstance(modes,list) or not modes or len(set(modes))!=len(modes):raise ValueError('Require distinct presentation modes')
    for mode in modes:permutation_mode(mode)
    rows,receipt=original_examples(source)
    if any(set(json.loads(row['completion'][0]['content']))!={'locations'} for row in rows):
        raise ValueError('Presentation augmentation requires a symbol-only source')
    built=[numbered_example(row,permutation=mode)[0] for row in rows for mode in modes]
    return rows,receipt,built,meta


def export_permutations(source,modes,output):
    from .scout_id_training import training_task_universe
    source,output=Path(source).resolve(),Path(output).resolve()
    rows,receipt,built,meta=rebuild(source,modes)
    output.mkdir(parents=True,exist_ok=False);atomic_json(output/'export.json',{'status':'incomplete'})
    (output/'development.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in built),encoding='utf-8')
    report={'status':'exported_development_only','representation':'permuted_candidate_ids','source':str(source),
        'modes':modes,'sample_count':len(built),'original_sample_count':len(rows),
        'source_tasks':training_task_universe(meta),'dataset_sha256':file_hash(output/'development.jsonl'),
        'inputs':{str(source/name):file_hash(source/name) for name in ('export.json','development.jsonl')},
        'scope':'Mechanically transformed presentations, not new tasks/labels; original logical teachers unchanged',
        'production_promoted':False}
    atomic_json(output/'export.json',report);restore_permutations(output,report)
    return report


def restore_permutations(dataset,meta):
    from .scout_id_training import training_task_universe
    dataset=Path(dataset)
    for path,h in meta['inputs'].items():
        if file_hash(path)!=h:raise ValueError('Permutation source changed')
    rows,receipt,built,source_meta=rebuild(meta['source'],meta['modes'])
    actual=[json.loads(line) for line in (dataset/'development.jsonl').read_text(encoding='utf-8').splitlines()]
    if (actual!=built or meta['sample_count']!=len(built) or meta['original_sample_count']!=len(rows) or
        meta['source_tasks']!=training_task_universe(source_meta) or
        file_hash(dataset/'development.jsonl')!=meta['dataset_sha256']):
        raise ValueError('Permutation teachers/lineage changed')
    return rows,receipt
