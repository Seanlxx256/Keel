"""Evidence-gated, minimal dependency-consumer version reconciliation."""
import hashlib
import json
import re
import shlex


def validate_policy(value):
    if not isinstance(value,dict) or set(value)!={'pins','anchors'}:
        raise ValueError('Compatibility policy requires exact pins and provider anchors')
    pins,anchors=value['pins'],value['anchors']
    if not isinstance(pins,dict) or not 1<=len(pins)<=3 or not isinstance(anchors,dict) or not 1<=len(anchors)<=20:
        raise ValueError('Require1..3 consumer pins and1..20 provider anchors')
    for name,version in [*pins.items(),*anchors.items()]:
        if not isinstance(name,str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name):
            raise ValueError('Invalid distribution identifier')
        if not isinstance(version,str) or not re.fullmatch(r'[0-9][A-Za-z0-9.!+_-]*',version):
            raise ValueError('Exact version required')
    if set(pins)&(set(anchors)|{'pip','setuptools','wheel','pytest','pluggy'}):
        raise ValueError('Cannot replace an anchor or verification/build tool')
    return value


def resolution_request(evidence,*,failure_text,handled_consumers=()):
    all_conflicts=evidence.get('conflicts',[])
    # Installed metadata commonly contains unrelated historical conflicts. Only
    # distributions on observed site-package traceback paths are repair targets.
    modules=set(re.findall(r'(?:site|dist)-packages[/\\]([A-Za-z_]\w*)(?=[/\\.]|:)',failure_text))
    mapping=evidence.get('module_distributions',{})
    related={name for module in modules for name in mapping.get(module,[])}
    conflicts=[x for x in all_conflicts if x['consumer'] in related and x['consumer'] not in handled_consumers]
    versions=evidence.get('versions',{})
    if not isinstance(versions,dict) or not 1<=len(versions)<=500:
        raise ValueError('Require bounded installed-version inventory')
    for name,version in versions.items():
        if (not isinstance(name,str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name)
                or not isinstance(version,str) or not re.fullmatch(r'[0-9][A-Za-z0-9.!+_-]*',version)):
            raise ValueError('Invalid installed-version inventory')
    if not conflicts:raise ValueError('No declared conflicts linked to observed failure paths')
    if len(conflicts)>20:raise ValueError('Failure-linked constraint scope exceeds supported size')
    consumers={x['consumer'] for x in conflicts}
    anchors={x['provider']:versions[x['provider']] for x in conflicts}
    pins={name:versions[name] for name in consumers}
    validate_policy({'pins':pins,'anchors':anchors})
    if consumers&set(evidence.get('editable_distributions',[])):
        raise ValueError('Never replace editable project distributions')
    return {'consumers':sorted(consumers),'anchors':anchors,'versions':versions,
            'scope_evidence':{'trace_modules':sorted(modules),'selected_conflicts':conflicts,
                'unrelated_or_handled_conflicts':[x for x in all_conflicts if x not in conflicts]}}


def validate_resolution(request,result):
    if result.get('status')!='resolved':raise ValueError('Resolver did not find a bounded plan')
    pins=result.get('pins')
    policy=validate_policy({'pins':pins,'anchors':request['anchors']})
    if set(pins)!=set(request['consumers']):raise ValueError('Resolver changed unauthorized distributions')
    if all(request['versions'].get(n)==v for n,v in pins.items()):raise ValueError('Resolver made no progress')
    return policy


RESOLVE_PROGRAM = r'''
import json,re,subprocess,sys,time
from pathlib import Path
from packaging.utils import canonicalize_name as canonical
request=json.loads(sys.argv[1])
constraints=Path('/tmp/keel-compat-constraints.txt')
report=Path('/tmp/keel-compat-resolver.json')
args=[sys.executable,'-m','pip','install','--upgrade','--dry-run','--report',str(report),
 '--only-binary=:all:','--cache-dir','/tmp/keel-pip-cache','--constraint',str(constraints),*request['consumers']]
try:
 deadline=time.monotonic()+150
 denied=set()
 result={'status':'resolution_scope_exhausted'}
 for round in range(3):
  constraints.write_text('\n'.join([n+'=='+v for n,v in request['versions'].items() if n not in request['consumers']]
      +[n+'<0' for n in sorted(denied)])+'\n')
  if report.exists():report.unlink()
  process=subprocess.run(args,capture_output=True,text=True,timeout=max(.01,deadline-time.monotonic()))
  if process.returncode or not report.is_file():
   result={'status':'resolution_unavailable','returncode':process.returncode};break
  rows=json.loads(report.read_text()).get('install',[])
  pins={canonical(x['metadata']['name']):x['metadata']['version'] for x in rows}
  extra=set(pins)-set(request['consumers'])
  if not extra:
   result={'status':'resolved','pins':pins,'resolver_rounds':round+1};break
  if extra & set(request['versions']):
   result={'status':'unauthorized_existing_package_change'};break
  if any(not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',n) for n in extra):
   result={'status':'invalid_resolver_package'};break
  # Excluding newly introduced dependencies lets the resolver backtrack to a
  # compatible consumer release without broadening the authorized mutation set.
  denied.update(extra)
except subprocess.TimeoutExpired:result={'status':'resolution_timed_out'}
print(json.dumps(result))
'''

APPLY_PROGRAM = r'''
import importlib.metadata as md,json,subprocess,sys
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name as canonical
policy=json.loads(sys.argv[1])
def versions():return {canonical(d.metadata['Name']):d.version for d in md.distributions() if d.metadata.get('Name')}
def conflicts(installed):
 issues=set()
 for d in md.distributions():
  for raw in d.requires or []:
   req=Requirement(raw)
   if req.marker is not None and not req.marker.evaluate({'extra':''}):continue
   provider=canonical(req.name)
   if provider not in installed or not req.specifier.contains(installed[provider],prereleases=True):
    issues.add((canonical(d.metadata['Name']),raw))
 return issues
before=versions()
existing=conflicts(before)
for name in policy['pins']:
 distribution=md.distribution(name)
 direct=json.loads(distribution.read_text('direct_url.json') or '{}')
 location=str(getattr(distribution,'locate_file',lambda _: '')(''))
 if direct.get('dir_info',{}).get('editable') or location=='/testbed' or location.startswith('/testbed/'):
  raise RuntimeError('Cannot replace editable project')
for name,version in policy['anchors'].items():
 if before.get(name)!=version:raise RuntimeError('Provider anchor changed: '+name)
subprocess.run([sys.executable,'-m','pip','install','--only-binary=:all:','--no-deps',
 *[n+'=='+v for n,v in policy['pins'].items()]],check=True,timeout=150)
after=versions()
if conflicts(after)-existing:raise RuntimeError('Reconciliation introduced dependency conflicts')
if any(after.get(n)!=v for n,v in before.items() if n not in policy['pins']):
 raise RuntimeError('Unplanned dependency mutation')
for name,version in policy['pins'].items():
 if after.get(name)!=version:raise RuntimeError('Consumer pin not applied')
 for raw in md.distribution(name).requires or []:
  req=Requirement(raw)
  if req.marker is not None and not req.marker.evaluate({'extra':''}):continue
  provider=canonical(req.name)
  if provider not in after or not req.specifier.contains(after[provider],prereleases=True):
   raise RuntimeError('Reconciled consumer still has unsatisfied requirement: '+str(req))
print('KEEL_COMPATIBILITY='+json.dumps({'pins':policy['pins'],'anchors':policy['anchors'],'validated':True}))
'''


def apply_compatibility_policy(spec,policy):
    validate_policy(policy)
    key=hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest()[:16]
    if getattr(spec,'_keel_compatibility',None)==key:return spec
    if getattr(spec,'_keel_compatibility',None) or getattr(spec,'_keel_overlay',None):
        raise ValueError('Cannot stack dependency reconciliations or packaging overlays')
    command='python -B -c '+shlex.quote(APPLY_PROGRAM)+' '+shlex.quote(json.dumps(policy))
    def modify(lines):
        result=[];count=0
        for line in lines:
            result.append(line)
            if line.startswith('python -m pip install'):
                result.append(command);count+=1
        return result,count
    repo,count=modify(spec.repo_script_list)
    if not count:raise ValueError('Unsupported repository installer')
    evaluation,_=modify(spec.eval_script_list)
    spec.repo_script_list=repo;spec.eval_script_list=evaluation
    spec.instance_image_tag+='-compat-'+key
    spec._keel_compatibility=key
    return spec


def install_compatibility_policy(policy):
    import sys
    import swebench.harness.test_spec.test_spec as module
    original=module.make_test_spec
    def make(*args,**kwargs):return apply_compatibility_policy(original(*args,**kwargs),policy)
    module.make_test_spec=make
    for name,loaded in list(sys.modules.items()):
        if name.startswith('swebench.harness.') and loaded is not None and getattr(loaded,'make_test_spec',None) is original:
            loaded.make_test_spec=make
