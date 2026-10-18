"""Restricted, explicit packaging overlays for reconstructed harness environments."""
import hashlib
import json
import re


TOOLS = {'pip', 'setuptools', 'wheel', 'flit_core', 'hatchling', 'poetry_core'}


def validate_overlay(value):
    if not isinstance(value, dict) or set(value) != {'pins', 'no_build_isolation', 'hypothesis', 'evidence', 'reason'}:
        raise ValueError('Expected pins, no_build_isolation, hypothesis, evidence, reason')
    if type(value['no_build_isolation']) is not bool or not isinstance(value['pins'], list) or not 1 <= len(value['pins']) <= 6:
        raise ValueError('Require 1..6 exact packaging-tool pins and boolean no_build_isolation')
    seen = set()
    for pin in value['pins']:
        match = re.fullmatch(r'([a-z_]+)==([0-9][A-Za-z0-9.]*?)', pin) if isinstance(pin, str) else None
        if not match or match[1] not in TOOLS or match[1] in seen:
            raise ValueError('Only unique exact packaging-tool pins allowed; no commands, URLs or project dependencies')
        seen.add(match[1])
    for key in ('hypothesis', 'evidence', 'reason'):
        if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 1500:
            raise ValueError('Diagnosis fields must be nonempty strings <=1500 characters')
    return value


def overlay_key(value):
    validate_overlay(value)
    return hashlib.sha256(json.dumps({'pins': sorted(value['pins']),
        'no_build_isolation': value['no_build_isolation']}, sort_keys=True).encode()).hexdigest()[:20]


def apply_overlay(spec, overlay):
    """Change installation only; preserve acceptance commands, labels and source."""
    key = overlay_key(overlay)
    if getattr(spec, '_keel_overlay', None) == key:
        return spec
    if getattr(spec, '_keel_overlay', None):
        raise ValueError('Cannot stack environment overlays')
    pins = sorted(overlay['pins'])
    constraint = '/tmp/keel-packaging-' + key + '.txt'
    bootstrap = ["printf '%s\\n' " + ' '.join("'"+p+"'" for p in pins) + ' > ' + constraint,
                 'python -m pip install ' + ' '.join(pins), 'export PIP_CONSTRAINT=' + constraint]
    def modify(lines):
        result, count = [], 0
        for line in lines:
            if re.match(r'^python -m pip install(?:\s|$)', line):
                result.extend(bootstrap)
                if overlay['no_build_isolation']:
                    line = line.replace('python -m pip install', 'python -m pip install --no-build-isolation', 1)
                count += 1
            result.append(line)
        return result, count
    repo, count = modify(spec.repo_script_list)
    if not count:
        raise ValueError('Unsupported installer: expected python -m pip install in repository setup')
    evaluation, _ = modify(spec.eval_script_list)
    spec.repo_script_list = repo
    spec.eval_script_list = evaluation
    spec.env_script_list = [*spec.env_script_list, '# Keel reconstructed packaging overlay ' + key]
    spec.instance_image_tag = 'keel-env-' + key
    spec._keel_overlay = key
    return spec


def install_overlay(overlay):
    """Installed only inside the isolated harness child process."""
    import swebench.harness.test_spec.test_spec as module
    original = module.make_test_spec
    def make(*args, **kwargs):
        return apply_overlay(original(*args, **kwargs), overlay)
    module.make_test_spec = make
    # Some harness modules retain imported aliases; patch only exact function aliases.
    import sys
    for name, loaded in list(sys.modules.items()):
        if name.startswith('swebench.harness.') and loaded is not None and getattr(loaded, 'make_test_spec', None) is original:
            loaded.make_test_spec = make
