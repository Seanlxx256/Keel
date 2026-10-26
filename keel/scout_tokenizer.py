"""Pinned tokenizer-only preparation and real full-template loss-boundary checks."""
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path

from compass.progress import atomic_json
from .scout_sft import completion_labels


MODEL='Qwen/Qwen3-0.6B'
REVISION='c1899de289a04d12100db370d81485cdf75e47ca'
ASSET_FILES=('config.json','tokenizer.json','tokenizer_config.json')
REQUIREMENTS=('transformers==4.57.6','jinja2==3.1.6')


def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment_receipt(output):
    import sys
    # Follow importlib's selected distribution, not last-wins enumeration of
    # shadowed metadata in an explicitly shared dependency source.
    visible={d.metadata['Name'] for d in metadata.distributions() if d.metadata.get('Name')}
    packages={name.lower():metadata.version(name) for name in visible}
    if packages.get('transformers')!='4.57.6' or packages.get('jinja2')!='3.1.6':
        raise ValueError('Tokenizer environment dependency pins changed')
    value={'python':sys.executable,'python_sha256':file_hash(sys.executable),'packages':packages,
           'scope':'Observed package versions/interpreter identity, not full reproducible OS environment'}
    atomic_json(Path(output)/'environment.json',value);return value


def download_assets(directory,cache):
    # Only explicit preparation uses the network; no tokens or model weights.
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
    from huggingface_hub import hf_hub_download
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    hashes={}
    for name in ASSET_FILES:
        print('[Scout tokenizer] download '+name,flush=True)
        source=Path(hf_hub_download(MODEL,name,revision=REVISION,cache_dir=str(cache),token=False))
        raw=source.read_bytes()
        if len(raw)>33554432:raise ValueError('Tokenizer asset exceeds resource bound')
        (directory/name).write_bytes(raw);hashes[name]=file_hash(directory/name)
    receipt={'model':MODEL,'revision':REVISION,'files':hashes,'model_weights_downloaded':False}
    atomic_json(directory/'assets.json',receipt);return receipt


def verify_assets(directory):
    directory=Path(directory);receipt=json.loads((directory/'assets.json').read_text(encoding='utf-8'))
    if receipt['model']!=MODEL or receipt['revision']!=REVISION or set(receipt['files'])!=set(ASSET_FILES):
        raise ValueError('Require pinned tokenizer asset identity')
    for name,expected in receipt['files'].items():
        if (directory/name).is_symlink() or file_hash(directory/name)!=expected:
            raise ValueError('Tokenizer asset changed')
    if json.loads((directory/'config.json').read_text(encoding='utf-8'))['model_type']!='qwen3':
        raise ValueError('Unexpected model configuration')
    return receipt


def encode_sample(tokenizer,example):
    prompt=example['prompt'];completion=example['completion']
    if len(completion)!=1 or completion[0]['role']!='assistant':raise ValueError('One assistant target required')
    target=completion[0]['content']
    prefix=tokenizer.apply_chat_template(prompt,tokenize=False,add_generation_prompt=True,enable_thinking=False)
    text=tokenizer.apply_chat_template(prompt+completion,tokenize=False,add_generation_prompt=False,enable_thinking=False)
    if not text.startswith(prefix) or not text[len(prefix):].startswith(target):
        raise ValueError('Chat template changed original target or generation prefix')
    # Encode the FULL rendered conversation once; offsets locate the target.
    encoded=tokenizer(text,add_special_tokens=False,return_offsets_mapping=True)
    ids=encoded['input_ids'];offsets=encoded['offset_mapping']
    if len(ids)!=len(offsets):raise ValueError('Token offset count mismatch')
    boundary=len(prefix);mask=[]
    for start,end in offsets:
        if start<boundary<end:raise ValueError('A token crosses the prompt/target boundary; template review required')
        mask.append(int(start>=boundary and end>start))
    labels=completion_labels(ids,mask)
    start=mask.index(1)
    # Independently verify actual generation prefill agrees with full encoding.
    prefill=tokenizer(prefix,add_special_tokens=False)['input_ids']
    if ids[:start]!=prefill:raise ValueError('Generation prefill differs from full-template token prefix')
    decoded=tokenizer.decode(ids[start:],skip_special_tokens=False,clean_up_tokenization_spaces=False)
    if decoded!=text[boundary:]:raise ValueError('Labelled tokens do not exactly decode to completion suffix')
    if tokenizer.eos_token_id not in ids[start:]:raise ValueError('Completion lacks trained EOS boundary')
    return {'input_ids':ids,'attention_mask':[1]*len(ids),'labels':labels,
        'metrics':{'input_tokens':len(ids),'prompt_tokens':start,'labelled_tokens':sum(mask),
            'template_eos_present':True,'generation_prefix_matches':True,'target_text_preserved':True}}


def check_dataset(data_dir,assets,output,*,loader=None):
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    os.environ['USE_TORCH']='0';os.environ['USE_TF']='0';os.environ['USE_FLAX']='0'
    assets=Path(assets);receipt=verify_assets(assets)
    data_dir,output=Path(data_dir),Path(output)
    exported=json.loads((data_dir/'export.json').read_text(encoding='utf-8'))
    source=data_dir/'development.jsonl';identity=file_hash(source)
    if exported['status']!='exported_development_only' or identity!=exported['dataset_sha256']:
        raise ValueError('Reviewed dataset identity changed')
    if loader is None:
        from transformers import AutoTokenizer
        loader=AutoTokenizer.from_pretrained
    tokenizer=loader(str(assets),local_files_only=True,trust_remote_code=False)
    if not getattr(tokenizer,'is_fast',False):raise ValueError('Fast tokenizer offsets required')
    report={'status':'running','model':MODEL,'revision':REVISION,'dataset_sha256':identity,
            'tokenizer_assets':receipt,'thinking':False,'model_calls':0,'weight_updates':0,
            'scope':'Real offline tokenizer/template/label check only; no GPU allocation, SFTTrainer or optimizer verification',
            'samples':[]}
    output.mkdir(parents=True,exist_ok=True)
    atomic_json(output/'check.json',report)
    for index,line in enumerate(source.read_text(encoding='utf-8').splitlines()):
        print(f'[Scout tokenizer] offline sample {index+1}',flush=True)
        encoded=encode_sample(tokenizer,json.loads(line))
        report['samples'].append({'index':index,**encoded['metrics']})
        atomic_json(output/'check.json',report)
    if len(report['samples'])!=exported['sample_count'] or not report['samples']:
        raise ValueError('Dataset sample count changed')
    if file_hash(source)!=identity:raise ValueError('Dataset changed during tokenizer check')
    verify_assets(assets)
    report['status']='passed';atomic_json(output/'check.json',report);return report
