"""Execute the unchanged official harness with Linux artifact transport on Windows."""
import os
from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.swebench_transport import linux_artifact_writes


if __name__ == '__main__':
    if os.environ.get('KEEL_HARNESS_NETWORK_POLICY'):
        from keel.harness_network import install_network_policy
        install_network_policy(os.environ['KEEL_HARNESS_NETWORK_POLICY'])
    if os.environ.get('KEEL_HARNESS_ENV_OVERLAY'):
        import json
        from keel.harness_environment import install_overlay
        install_overlay(json.loads(Path(os.environ['KEEL_HARNESS_ENV_OVERLAY']).read_text(encoding='utf-8')))
    if os.environ.get('KEEL_HARNESS_PLUGIN_POLICY'):
        from keel.harness_plugins import install_plugin_policy
        install_plugin_policy(os.environ['KEEL_HARNESS_PLUGIN_POLICY'])
    if os.environ.get('KEEL_HARNESS_CACHE_SCOPE'):
        from keel.harness_cache import install_cache_scope
        install_cache_scope(os.environ['KEEL_HARNESS_CACHE_SCOPE'])
    if os.name == 'nt':
        with linux_artifact_writes():
            runpy.run_module('swebench.harness.run_evaluation', run_name='__main__', alter_sys=True)
    else:
        runpy.run_module('swebench.harness.run_evaluation', run_name='__main__', alter_sys=True)
