"""Registered SCM entry-point collision recovery, confined to harness containers."""
import json

POLICY = 'remove_unused_vcs_versioning'
PROGRAM = r'''
import importlib.metadata as md,json,subprocess,sys,warnings
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import setuptools_scm
from setuptools_scm.git import parse
scheme='release-branch-semver'
providers=[(d,e) for d in md.distributions() for e in d.entry_points
 if e.group=='setuptools_scm.version_scheme' and e.name==scheme]
removed=False
if any(canonicalize_name(d.metadata['Name'])=='vcs-versioning' for d,e in providers):
 dependents=[]
 for d in md.distributions():
  for raw in d.requires or []:
   req=Requirement(raw)
   if canonicalize_name(req.name)=='vcs-versioning' and (req.marker is None or req.marker.evaluate()):
    dependents.append(d.metadata['Name'])
 if dependents: raise RuntimeError('Conflicting provider is required by: '+str(dependents))
 version=parse('/testbed')
 outcomes={}
 for d,e in providers:
  try:
   with warnings.catch_warnings():
    warnings.simplefilter('error',DeprecationWarning)
    e.load()(version)
   outcomes[canonicalize_name(d.metadata['Name'])]='passed'
  except DeprecationWarning: outcomes[canonicalize_name(d.metadata['Name'])]='deprecation'
 if outcomes.get('setuptools-scm')!='passed' or outcomes.get('vcs-versioning')!='deprecation':
  raise RuntimeError('SCM collision applicability check did not reproduce')
 before=subprocess.run([sys.executable,'-m','pip','check'],capture_output=True,text=True,timeout=30)
 subprocess.run([sys.executable,'-m','pip','uninstall','-y','vcs-versioning'],check=True,timeout=60)
 after=subprocess.run([sys.executable,'-m','pip','check'],capture_output=True,text=True,timeout=30)
 existing=set(before.stdout.splitlines()) if before.returncode else set()
 introduced=set(after.stdout.splitlines())-existing if after.returncode else set()
 if after.returncode not in (0,1) or introduced or (after.returncode and not after.stdout.strip()):
  raise RuntimeError('Dependency validation failed after removal: '+str(sorted(introduced)))
 print('KEEL_PLUGIN_DEPENDENCIES='+json.dumps({'before_returncode':before.returncode,
  'after_returncode':after.returncode,'preexisting_issues':sorted(existing),'new_issues':sorted(introduced)}))
 removed=True
# A fresh interpreter prevents in-process metadata caches from retaining removed providers.
verify="import setuptools_scm,warnings; warnings.simplefilter('error',DeprecationWarning); print(setuptools_scm.get_version(root='/testbed',version_scheme='release-branch-semver'))"
subprocess.run([sys.executable,'-B','-c',verify],check=True,timeout=30)
print('KEEL_PLUGIN_REPAIR='+json.dumps({'policy':'remove_unused_vcs_versioning','removed':removed,'version_check_passed':True}))
'''


def apply_plugin_policy(spec, policy):
    if policy != POLICY:
        raise ValueError('Unsupported plugin recovery policy')
    if getattr(spec,'_keel_plugin_policy',None)==policy:
        return spec
    if getattr(spec,'_keel_overlay',None):
        raise ValueError('Plugin recovery cannot stack with packaging overlays')
    command='python -B -c '+__import__('shlex').quote(PROGRAM)
    def modify(lines):
        result=[]; count=0
        for line in lines:
            result.append(line)
            if line.startswith('python -m pip install'):
                result.append(command); count+=1
        return result,count
    repo,count=modify(spec.repo_script_list)
    if not count:
        raise ValueError('Expected a supported repository installer')
    evaluation,_=modify(spec.eval_script_list)
    spec.repo_script_list=repo
    spec.eval_script_list=evaluation
    spec.instance_image_tag=spec.instance_image_tag+'-scm-recovery-v1'
    spec._keel_plugin_policy=policy
    return spec


def install_plugin_policy(policy):
    import sys
    import swebench.harness.test_spec.test_spec as module
    original=module.make_test_spec
    def make(*args,**kwargs):
        return apply_plugin_policy(original(*args,**kwargs),policy)
    module.make_test_spec=make
    for name,loaded in list(sys.modules.items()):
        if name.startswith('swebench.harness.') and loaded is not None and getattr(loaded,'make_test_spec',None) is original:
            loaded.make_test_spec=make
