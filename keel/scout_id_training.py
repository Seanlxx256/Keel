"""Explicit development encoding migration; preserve logical teacher selections."""
import json
from pathlib import Path
from compass.progress import atomic_json
from .scout_candidate_ids import numbered_example, decode_ids, lookup_example
from .scout_tokenizer import file_hash


def original_examples(dataset):
    """Recover and revalidate the exact logical scoring cohort before inference."""
    dataset = Path(dataset)
    exported = json.loads((dataset/'export.json').read_text(encoding='utf-8'))
    if exported.get('representation')=='permuted_candidate_ids':
        from .scout_permutation_data import restore_permutations
        return restore_permutations(dataset,exported)
    if exported.get('representation')=='subset_candidate_ids':
        for path,identity in exported['inputs'].items():
            if file_hash(path)!=identity:raise ValueError('Subset source changed')
        source=Path(exported['subset_source'])
        meta=json.loads((source/'export.json').read_text())
        if meta['representation']!='mixed_files_candidate_ids' or exported['source_tasks']!=meta.get('tasks'):
            raise ValueError('Subset training task provenance changed')
        rows,receipt=original_examples(source)
        indices=validate_subset_indices(exported['source_indices'],len(rows))
        encoded=[json.loads(line) for line in (source/'development.jsonl').read_text(encoding='utf-8').splitlines()]
        actual=[json.loads(line) for line in (dataset/'development.jsonl').read_text(encoding='utf-8').splitlines()]
        if (actual!=[encoded[i] for i in indices] or exported['sample_count']!=len(indices) or
                file_hash(dataset/'development.jsonl')!=exported['dataset_sha256']):
            raise ValueError('Subset targets/lineage changed')
        return [rows[i] for i in indices],receipt
    if exported.get('representation') in ('lookup_only_candidate_ids','lookup_diverse_candidate_ids'):
        for path,identity in exported['inputs'].items():
            if file_hash(path)!=identity:raise ValueError('Lookup source changed')
        source=Path(exported['lookup_source'])
        meta=json.loads((source/'export.json').read_text(encoding='utf-8'))
        if meta['representation']!='mixed_files_candidate_ids':raise ValueError('Require plain ID lookup source')
        rows,receipt=original_examples(source)
        indices=[i for i,row in enumerate(rows) if set(json.loads(row['completion'][0]['content']))=={'locations'}]
        if exported['representation']=='lookup_diverse_candidate_ids':
            from .scout_lookup_data import lookup_variants
            built=[lookup_variants(rows[i]) for i in indices]
            expected=[row for batch,_ in built for row in batch]
            if exported['query_manifests']!=[{'sample':i,**info} for i,(_,info) in zip(indices,built)]:
                raise ValueError('Lookup query manifest changed')
        else:expected=[lookup_example(rows[i],presentation='without_goal')[0] for i in indices]
        actual=[json.loads(line) for line in (dataset/'development.jsonl').read_text(encoding='utf-8').splitlines()]
        if (actual!=expected or exported['sample_count']!=len(expected) or
            exported['original_sample_count']!=len(rows) or exported['tasks']!=meta['tasks'] or
            exported['lookup_original_indices']!=indices or file_hash(dataset/'development.jsonl')!=exported['dataset_sha256']):
            raise ValueError('Lookup-only targets/lineage changed')
        return rows,receipt
    auxiliary = exported.get('representation') == 'mixed_files_candidate_ids_with_lookup'
    if exported.get('representation') not in ('mixed_files_candidate_ids','mixed_files_candidate_ids_with_lookup'):
        raise ValueError('Require explicit ID encoding migration')
    for path, identity in exported.get('auxiliary_source_inputs', {}).items():
        if file_hash(path) != identity:raise ValueError('Auxiliary source changed')
    for path, identity in exported['inputs'].items():
        if file_hash(path) != identity:
            raise ValueError('Original scoring source changed')
    sources = [Path(path) for path in exported['inputs'] if Path(path).name == 'development.jsonl']
    if len(sources) != 1:
        raise ValueError('Ambiguous original scoring cohort')
    original = sources[0]
    rows = [json.loads(line) for line in original.read_text(encoding='utf-8').splitlines()]
    actual = [json.loads(line) for line in (dataset/'development.jsonl').read_text(encoding='utf-8').splitlines()]
    count = exported.get('original_sample_count', exported['sample_count'])
    if len(rows) != count or len(actual) != exported['sample_count']:
        raise ValueError('Scoring cohort incomplete')
    if file_hash(dataset/'development.jsonl') != exported['dataset_sha256']:
        raise ValueError('Encoded cohort changed')
    if file_hash(dataset/'mappings.json') != exported['mappings_sha256']:
        raise ValueError('Mapping receipt changed')
    mappings = []
    for index, row in enumerate(rows):
        if set(json.loads(row['completion'][0]['content'])) == {'locations'}:
            expected, mapping, spec = numbered_example(row)
            mappings.append({'sample': index, 'mapping': mapping, 'spec': spec})
        else:
            expected = row
        if actual[index] != expected:
            raise ValueError('Encoded prompt/teacher differs from original')
    if auxiliary:
        indices=[i for i,row in enumerate(rows) if set(json.loads(row['completion'][0]['content']))=={'locations'}]
        expected_tail=[lookup_example(rows[i],presentation='without_goal')[0] for i in indices]
        if actual[count:]!=expected_tail or exported['auxiliary_original_indices']!=indices:
            raise ValueError('Auxiliary lookup targets changed')
    elif len(actual)!=len(rows):raise ValueError('Unexpected extra training rows')
    receipt = json.loads((dataset/'mappings.json').read_text(encoding='utf-8'))
    if receipt != {'rows': mappings, 'source_dataset_sha256': file_hash(original)}:
        raise ValueError('Mapping does not match original catalog')
    return rows, {'path': str(original), 'sha256': file_hash(original),
                  'encoding': 'Original logical targets; ID encoding applied exactly once'}


def validate_subset_indices(indices,count):
    if (not isinstance(indices,list) or not indices or any(type(i) is not int or not 0<=i<count for i in indices)
            or len(set(indices))!=len(indices)):
        raise ValueError('Require unique in-range subset indices')
    return indices


def training_task_universe(exported):
    """Conservative disjointness guard: subset retains its entire source task set."""
    if exported.get('representation') in ('subset_candidate_ids','permuted_candidate_ids'):
        return exported['source_tasks']
    return exported['tasks']


def export_subset(source,indices,output):
    """Exact training-row subset for fit diagnostics, never relabel or prune catalogs."""
    source,output=Path(source).resolve(),Path(output).resolve()
    rows,_=original_examples(source)
    meta=json.loads((source/'export.json').read_text())
    if meta['representation']!='mixed_files_candidate_ids':raise ValueError('Require plain ID source')
    indices=validate_subset_indices(indices,len(rows))
    raw=(source/'development.jsonl').read_bytes().splitlines(keepends=True)
    output.mkdir(parents=True,exist_ok=False)
    atomic_json(output/'export.json',{'status':'incomplete'})
    (output/'development.jsonl').write_bytes(b''.join(raw[i] for i in indices))
    report={'status':'exported_development_only','representation':'subset_candidate_ids',
            'sample_count':len(indices),'subset_source':str(source),'source_indices':indices,
            'source_tasks':meta.get('tasks'),
            'dataset_sha256':file_hash(output/'development.jsonl'),
            'inputs':{str(source/name):file_hash(source/name) for name in ('export.json','development.jsonl','mappings.json')},
            'scope':'Exposed fit-control subset; exact existing teacher/catalog bytes, not new labels or transfer',
            'production_promoted':False}
    atomic_json(output/'export.json',report);original_examples(output)
    return report


def export_auxiliary(source, output):
    """Append mechanical lookup targets only from approved training catalogs."""
    source,output=Path(source).resolve(),Path(output).resolve()
    rows,_=original_examples(source)
    exported=json.loads((source/'export.json').read_text(encoding='utf-8'))
    if exported['representation']!='mixed_files_candidate_ids':raise ValueError('Require plain ID source')
    indices=[i for i,row in enumerate(rows) if set(json.loads(row['completion'][0]['content']))=={'locations'}]
    targets=[lookup_example(rows[i],presentation='without_goal')[0] for i in indices]
    raw=(source/'development.jsonl').read_bytes()
    if not raw.endswith(b'\n'):raise ValueError('Require complete original JSONL prefix')
    output.mkdir(parents=True,exist_ok=False)
    atomic_json(output/'export.json',{'status':'incomplete'})
    (output/'development.jsonl').write_bytes(raw+''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in targets).encode())
    (output/'mappings.json').write_bytes((source/'mappings.json').read_bytes())
    report={**exported,'representation':'mixed_files_candidate_ids_with_lookup',
            'sample_count':len(rows)+len(targets),'original_sample_count':len(rows),
            'auxiliary_original_indices':indices,'dataset_sha256':file_hash(output/'development.jsonl'),
            'auxiliary_source_inputs':{str(source/name):file_hash(source/name) for name in ('export.json','development.jsonl','mappings.json')},
            'scope':'Original repair prefix plus mechanically generated training-catalog lookup; reserved transfer excluded; no promotion'}
    atomic_json(output/'export.json',report)
    original_examples(output)
    return report


def export_lookup_only(source, output, *, diverse=False):
    """Development learnability diagnostic, not repair-data replacement."""
    source,output=Path(source).resolve(),Path(output).resolve()
    rows,_=original_examples(source)
    meta=json.loads((source/'export.json').read_text(encoding='utf-8'))
    if meta['representation']!='mixed_files_candidate_ids':raise ValueError('Require plain ID source')
    indices=[i for i,row in enumerate(rows) if set(json.loads(row['completion'][0]['content']))=={'locations'}]
    if diverse:
        from .scout_lookup_data import lookup_variants
        built=[lookup_variants(rows[i]) for i in indices]
        targets=[row for batch,_ in built for row in batch]
    else:targets=[lookup_example(rows[i],presentation='without_goal')[0] for i in indices]
    output.mkdir(parents=True,exist_ok=False)
    atomic_json(output/'export.json',{'status':'incomplete'})
    (output/'development.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in targets),encoding='utf-8')
    report={'status':'exported_development_only','representation':'lookup_diverse_candidate_ids' if diverse else 'lookup_only_candidate_ids',
            'sample_count':len(targets),'original_sample_count':len(rows),'tasks':meta['tasks'],
            'lookup_original_indices':indices,'lookup_source':str(source),
            'dataset_sha256':file_hash(output/'development.jsonl'),
            'inputs':{str(source/name):file_hash(source/name) for name in ('export.json','development.jsonl','mappings.json')},
            'scope':'Mechanical training-catalog lookup only; original repair source retained; no promotion'}
    if diverse:report['query_manifests']=[{'sample':i,**info} for i,(_,info) in zip(indices,built)]
    atomic_json(output/'export.json',report);original_examples(output)
    return report


def export_ids(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    exported = json.loads((source/'export.json').read_text(encoding='utf-8'))
    original = source/'development.jsonl'
    if (exported['status'] != 'exported_development_only' or
            exported['dataset_sha256'] != file_hash(original)):
        raise ValueError('Require unchanged development training export')
    for path, identity in exported.get('inputs', {}).items():
        if file_hash(path) != identity:
            raise ValueError('Source approval/input drift')
    rows = [json.loads(line) for line in original.read_text(encoding='utf-8').splitlines()]
    if len(rows) != exported['sample_count']:
        raise ValueError('Source count mismatch')
    converted, mappings = [], []
    for index, row in enumerate(rows):
        target = json.loads(row['completion'][0]['content'])
        if set(target) == {'locations'}:
            actual, mapping, spec = numbered_example(row)
            if json.loads(decode_ids(actual['completion'][0]['content'], mapping, spec)) != target:
                raise ValueError('Teacher roundtrip changed')
            mappings.append({'sample': index, 'mapping': mapping, 'spec': spec})
        elif set(target) == {'files'}:
            actual = row
        else:
            raise ValueError('Unsupported training stage')
        converted.append(actual)
    if not mappings:
        raise ValueError('No symbol examples to migrate')
    # Validate everything before publishing; never overwrite the original dataset.
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'incomplete', 'production_promoted': False,
              'scope': 'Encoding-only exposed development migration; no new labels or transfer training'}
    atomic_json(output/'export.json', report)
    (output/'development.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in converted), encoding='utf-8')
    atomic_json(output/'mappings.json', {'rows': mappings, 'source_dataset_sha256': file_hash(original)})
    inputs = {str(source/name): file_hash(source/name) for name in ('export.json', 'development.jsonl')}
    report.update(status='exported_development_only', sample_count=len(rows), tasks=exported['tasks'],
                  dataset_sha256=file_hash(output/'development.jsonl'), inputs=inputs,
                  source_export=exported, representation='mixed_files_candidate_ids',
                  transformed_samples=[row['sample'] for row in mappings],
                  mappings_sha256=file_hash(output/'mappings.json'))
    atomic_json(output/'export.json', report)
    return report
