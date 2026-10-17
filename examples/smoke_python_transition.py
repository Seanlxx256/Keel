"""Zero-model-call Docker control for a CPython 3.11 -> 3.12 API migration.

Synthetic environment smoke test only; no benchmark or Keel repair-score claim.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.core import Budget, Limits
from keel.task_factory import construct

RECIPE = {'kind': 'python', 'python': '3.12', 'old': '3.11', 'new': '3.12', 'common': [
    'pip==24.0', 'setuptools==68.2.2', 'wheel==0.41.3', 'pytest==7.4.4',
    'iniconfig==2.0.0', 'packaging==23.2', 'pluggy==1.3.0']}
BASE = '''import socket
import ssl

def make_socket():
    return ssl.wrap_socket(socket.socket(), do_handshake_on_connect=False)
'''
GOLD = '''import socket
import ssl

def make_socket():
    return ssl.create_default_context().wrap_socket(
        socket.socket(), server_hostname="localhost", do_handshake_on_connect=False)
'''
TESTS = '''import ssl
import compatibility

def test_import():
    assert callable(compatibility.make_socket)

def test_socket_construction_without_connection():
    wrapped = compatibility.make_socket()
    try:
        assert isinstance(wrapped, ssl.SSLSocket)
    finally:
        wrapped.close()
'''


def execute(output):
    output.mkdir(parents=True, exist_ok=False)
    for name, code in [('base', BASE), ('gold', GOLD)]:
        root = output/name
        (root/'tests').mkdir(parents=True)
        (root/'compatibility.py').write_text(code, encoding='utf-8')
        tests = TESTS if name == 'gold' else TESTS.split('def test_socket_construction_without_connection')[0]
        (root/'tests/test_compatibility.py').write_text(tests, encoding='utf-8')
    class FixedPlanner:
        budget = Budget(Limits(max_wallclock=900, max_tool_calls=20))
        def plan(self, evidence, observation):
            return RECIPE
    planner = FixedPlanner()
    result, _ = construct({'title': 'Python 3.12 compatibility synthetic control'},
                          output/'base', output/'gold', output/'factory', planner, attempts=1)
    report = {'status': result['status'], 'passed': result['status'] == 'transition_verified',
              'model_calls': planner.budget.model_calls, 'budget': planner.budget.report(), 'benchmark_ready': False,
              'scope': 'Synthetic no-connection SSL socket construction; validates environment axis, not agent repair or production TLS.',
              'factory_result': str(output/'factory/factory.json')}
    (output/'smoke.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true', help='Build/pull Docker images and packages; no model/API key needed')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'status': 'plan_only', 'recipe': RECIPE, 'model_calls': 0, 'benchmark_ready': False}, indent=2))
        return 0
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
    report = execute(args.output.resolve())
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
