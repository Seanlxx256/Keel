"""Explicit APT transport adaptation; acceptance and package selection stay intact."""


def apply_network_policy(spec, policy):
    if policy not in ('no_pipeline','retry_acquire'):
        raise ValueError('Only registered isolated APT policies are supported')
    if getattr(spec, '_keel_network_policy', None) == policy:
        return spec
    if getattr(spec, '_keel_network_policy', None):
        raise ValueError('Cannot stack network policies')
    lines = list(spec.repo_script_list)
    if not any(line.lstrip().startswith('apt-get ') for line in lines):
        raise ValueError('No supported standalone APT command in repository setup')
    result = []
    for line in lines:
        if line.lstrip().startswith('apt-get '):
            from .apt_transport import transport_prefix
            result.extend(transport_prefix(policy).splitlines())
        result.append(line)
    spec.repo_script_list = result
    spec.instance_image_tag = 'keel-network-'+('no-pipeline' if policy=='no_pipeline' else 'retry-acquire')+'-v1'
    spec._keel_network_policy = policy
    return spec


def install_network_policy(policy):
    import sys
    import swebench.harness.test_spec.test_spec as module
    original = module.make_test_spec
    def make(*args, **kwargs):
        return apply_network_policy(original(*args, **kwargs), policy)
    module.make_test_spec = make
    for name, loaded in list(sys.modules.items()):
        if name.startswith('swebench.harness.') and loaded is not None and getattr(loaded, 'make_test_spec', None) is original:
            loaded.make_test_spec = make
