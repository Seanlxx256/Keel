import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from keel.models import Reply
from keel.runtime import run
from keel.verification_infrastructure import docker_health, infrastructure_failures


class InfrastructureTests(unittest.TestCase):
    def test_only_structured_unavailable_results_trigger_guard(self):
        self.assertFalse(infrastructure_failures([{'returncode': 1, 'stdout': 'Docker 503'}]))
        self.assertFalse(infrastructure_failures([{'returncode': 1, 'stdout': json.dumps({
            'official_resolved': False, 'failure_kind': 'test_failure', 'grading_status': 'graded'})}]))
        self.assertTrue(infrastructure_failures([{'returncode': 2, 'stdout': json.dumps({
            'official_resolved': None, 'grading_status': 'infrastructure_error'})}]))

    def test_unavailable_verifier_never_requests_critic_or_another_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'module.py').write_text('def version():\n    return 1\n')
            replies = [{'files': ['module.py']}, {'locations': ['module.py:1']},
                       {'summary': 'change', 'edits': [{'path': 'module.py', 'old': 'return 1', 'new': 'return 2'}]}]
            class Model:
                calls = 0
                def complete_json(self, messages, **kwargs):
                    self.calls += 1
                    return Reply(json.dumps(replies[self.calls-1]), 10)
            model = Model()
            command = [sys.executable, '-c', 'import json,sys; print(json.dumps(dict(official_resolved=None, failure_kind="grading_error"))); sys.exit(2)']
            config = {'mode': 'localized-proposal', 'goal': 'Return 2',
                      'recovery': {'strategy': 'adaptive', 'max_actions': 6, 'write_roots': ['.']},
                      'verification_infrastructure_retries': 1, 'acceptance': [command]}
            with patch('keel.verification_infrastructure.time.sleep'):
                result = run(config, root, root/'.keel/run', model=model)
            self.assertEqual(result['failure']['category'], 'environment_blocked')
            self.assertEqual(model.calls, 3)
            self.assertEqual(len(result['infrastructure_attempts']), 2)
            self.assertEqual(len({r['candidate_sha256'] for r in result['infrastructure_attempts']}), 1)
            self.assertEqual(result.get('recovery_decisions', []), [])
            self.assertIn('return 2', (root/'module.py').read_text())

    def test_transient_failure_rechecks_same_candidate_then_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'module.py').write_text('value = 1\n')
            unavailable = {'returncode': 2, 'stdout': json.dumps({'official_resolved': None, 'failure_kind': 'grading_timeout'}), 'stderr': ''}
            passed = {'returncode': 0, 'stdout': '', 'stderr': ''}
            config = {'goal': 'check', 'acceptance': [[sys.executable, '-c', 'pass']],
                      'verification_infrastructure_retries': 1}
            with patch('keel.workspace.Workspace.verify', side_effect=[[unavailable], [passed]]) as verify, \
                    patch('keel.verification_infrastructure.time.sleep'):
                result = run(config, root, root/'.keel/run')
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(len(result['verification_attempts']), 1)
            self.assertEqual(len(result['infrastructure_attempts']), 1)
            self.assertEqual((root/'module.py').read_text(), 'value = 1\n')

    def test_retries_use_shared_tool_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'module.py').write_text('value = 1\n')
            config = {'goal': 'check', 'acceptance': [[sys.executable, '-c',
                'import json,sys; print(json.dumps(dict(official_resolved=None, failure_kind="grading_error"))); sys.exit(2)']],
                'verification_infrastructure_retries': 1, 'budget': {'max_tool_calls': 1}}
            with patch('keel.verification_infrastructure.time.sleep'):
                result = run(config, root, root/'.keel/run')
            self.assertEqual(result['failure']['category'], 'budget_exhausted')
            self.assertEqual(result['budget']['tool_calls'], 1)

    def test_docker_client_alone_is_not_ready(self):
        with patch('keel.verification_infrastructure.subprocess.run', return_value=SimpleNamespace(
                returncode=1, stdout='', stderr='Server unavailable')):
            self.assertFalse(docker_health()['ready'])
        with patch('keel.verification_infrastructure.subprocess.run', return_value=SimpleNamespace(
                returncode=0, stdout='"29.8.2"\n', stderr='')):
            self.assertTrue(docker_health()['ready'])
        with patch('keel.verification_infrastructure.subprocess.run', side_effect=subprocess.TimeoutExpired('docker', 8)):
            self.assertFalse(docker_health()['ready'])
