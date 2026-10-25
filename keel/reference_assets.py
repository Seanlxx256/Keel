"""Discover validated preparation assets, never reuse an old acceptance score."""
import hashlib
import json
from pathlib import Path
import re
import time

from .evaluation_protocol import file_hash


def discover_assets(roots, record, failed, script, base, *, inspect_image, seconds):
    from .reference_pipeline import _grade_record, _files
    from .apt_archive_bridge import validate_artifact
    from .environment_probe import retained_image
    from .harness_cache import validate_scope
    from examples.run_swebench_task import reference_policies
    from examples.check_repository_network import extract_apt
    deadline=time.monotonic()+seconds
    expected=reference_policies(failed)
    prior_archive=expected.pop('apt_archives',None)
    expected['network_policy']='retry_acquire'
    command_hash=hashlib.sha256(extract_apt(script.read_text(encoding='utf-8')).encode()).hexdigest()
    result={'selected':None,'rejected':[],
        'scope':'Explicit evidence roots and direct children only; existing score is eligibility evidence, fresh grading required'}
    directories=set()
    for root in roots:
        root=Path(root).resolve()
        if not root.is_dir():raise ValueError('Preparation evidence root unavailable: '+str(root))
        directories.add(root)
        for path in root.iterdir():
            if time.monotonic()>=deadline:raise TimeoutError('Preparation discovery deadline')
            if len(directories)>=256:raise ValueError('Preparation discovery inventory too broad; narrow evidence roots')
            if path.is_dir() and not path.is_symlink():directories.add(path)
    for directory in sorted(directories):
        if time.monotonic()>=deadline:raise TimeoutError('Preparation discovery deadline')
        if not (directory/'grading.json').is_file():continue
        try:
            grade=_grade_record(directory,record)
            if grade.get('status')!='graded' or grade.get('official_resolved') is not True or not grade.get('report_sha256'):
                raise ValueError('Freshly verified reference evidence required')
            official=next((directory/'logs/run_evaluation').rglob('report.json'))
            if json.loads(official.read_text(encoding='utf-8')).get(record['instance_id'],{}).get('resolved') is not True:
                raise ValueError('Official report does not confirm resolution')
            # Compare registered policies by content, not their location.
            policies=reference_policies(directory)
            artifact_path=Path(policies.pop('apt_archives'))
            for key in set(expected)|set(policies):
                left,right=expected.get(key),policies.get(key)
                if key=='compatibility_policy':
                    left=json.loads(Path(left).read_text(encoding='utf-8')) if left else None
                    right=json.loads(Path(right).read_text(encoding='utf-8')) if right else None
                if left!=right:raise ValueError('Preparation policy mismatch: '+key)
            artifact=validate_artifact(json.loads(artifact_path.read_text(encoding='utf-8')))
            if prior_archive and json.loads(Path(prior_archive).read_text(encoding='utf-8'))!=artifact:
                raise ValueError('Cannot replace existing archive policy')
            if artifact['base_image']!=base or artifact['apt_command_sha256']!=command_hash:
                raise ValueError('Preparation APT workload mismatch')
            cache=grade.get('instance_cache',{})
            if cache.get('cache_level')!='instance':raise ValueError('Instance image was not retained')
            scope=validate_scope(cache.get('scope'))
            files=_files(directory)
            hashes={str(p):file_hash(p) for p in files}
            for name,identity in [(base,artifact['base_image_id']),(artifact['image'],artifact['image_id'])]:
                if inspect_image(name,max(0.001,deadline-time.monotonic()))!=identity:
                    raise ValueError('Preparation image identity changed')
            logs=list((directory/'logs/build_images/instances').glob('*/build_image.log'))
            if len(logs)!=1:raise ValueError('Require one completed instance build')
            text=logs[0].read_text(encoding='utf-8',errors='replace')
            match=re.search(r'Successfully built ([a-f0-9]{12,64})',text)
            if not match or 'Image built successfully!' not in text:raise ValueError('Completed instance provenance unavailable')
            instance=inspect_image(retained_image(directory),max(0.001,deadline-time.monotonic()))
            if not re.fullmatch(r'sha256:[a-f0-9]{64}',instance) or not instance.startswith('sha256:'+match[1]):
                raise ValueError('Retained instance image changed')
            if time.monotonic()>=deadline:raise TimeoutError('Preparation discovery deadline')
            if any(file_hash(Path(p))!=h for p,h in hashes.items()):raise ValueError('Preparation evidence changed during discovery')
            result['selected']={'grade':str(directory),'apt_archives':str(artifact_path),
                'instance_cache_scope':scope,'instance_image_id':instance,'inputs':hashes}
            return result
        except (ValueError,KeyError,OSError) as error:
            result['rejected'].append({'grade':str(directory),'reason':str(error)[:500]})
    return result
