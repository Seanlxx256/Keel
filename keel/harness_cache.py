"""Isolate retained official instance images by session and generated recipe."""
import hashlib
import json
import re


def validate_scope(scope):
    if not isinstance(scope, str) or not re.fullmatch(r'[a-f0-9]{32}', scope):
        raise ValueError('Instance cache scope must be 32 lowercase hex characters')
    return scope


def apply_cache_scope(spec, scope):
    validate_scope(scope)
    if getattr(spec, '_keel_cache_scope', None) == scope:
        return spec
    if getattr(spec, '_keel_cache_scope', None):
        raise ValueError('Cannot stack instance cache scopes')
    recipe = {'scope': scope, 'base': spec.base_image_key, 'environment': spec.env_image_key,
              'dockerfile': spec.instance_dockerfile, 'repo_script': spec.repo_script_list,
              'env_script': spec.env_script_list, 'policy_tag': spec.instance_image_tag}
    key = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()[:24]
    spec.instance_image_tag = 'keel-cache-' + key
    spec._keel_cache_scope = scope
    return spec


def install_cache_scope(scope):
    import sys
    import swebench.harness.test_spec.test_spec as module
    validate_scope(scope)
    original = module.make_test_spec
    def make(*args, **kwargs):
        return apply_cache_scope(original(*args, **kwargs), scope)
    module.make_test_spec = make
    for name, loaded in list(sys.modules.items()):
        if name.startswith('swebench.harness.') and loaded is not None and getattr(loaded, 'make_test_spec', None) is original:
            loaded.make_test_spec = make
