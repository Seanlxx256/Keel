import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from examples.run_agent_baseline import controls, prepare, summarize, trace_metrics


class AgentBaselineTests(unittest.TestCase):
    def test_unregistered_real_task_cannot_silently_enter_diagnostic_suite(self):
        spec = {**controls()[0], 'id': 'unknown-real-task', 'group': 'real_compatibility'}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'unknown'
            with self.assertRaisesRegex(ValueError, 'registered'):
                prepare(output, [spec], 'image', 'model', strategy='proposal')
            self.assertFalse(output.exists())

    def test_preparation_rejects_oversized_source_and_records_narrowed_preflight(self):
        from keel.core import BudgetExceeded
        source = ('# httpx type annotation padding\n' * 500 +
                  'class TestClient(object):\n    def __init__(self):\n        super().__init__()\n')
        spec = {**controls()[0], 'files': {'app.py': source.encode()},
                'queries': ['httpx']}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(BudgetExceeded, 'input bytes; limit is 12000'):
                prepare(root/'wide', [spec], 'image', 'model', strategy='proposal')
            self.assertFalse((root/'wide/tasks').exists())
            spec['queries'] = ['class TestClient(', 'super().__init__(']
            manifest = prepare(root/'narrow', [spec], 'image', 'model', strategy='proposal')
            check = manifest['tasks'][0]['context_preflight']
            self.assertLess(check['source_input_bytes'], check['limit_bytes'])
            self.assertFalse(check['dependency_evidence_included'])

    def test_trace_exposes_errors_hidden_by_terminal_turn_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'trace.jsonl'
            events = [{'event': 'tool_or_protocol_error'},
                {'event': 'gateway_call_started', 'tool': 'read_lines'},
                {'event': 'gateway_call_finished', 'status': 'failed'},
                {'event': 'tool_or_protocol_error'}]
            path.write_text('\n'.join(json.dumps(event) for event in events), encoding='utf-8')
            metrics = trace_metrics(path)
            self.assertEqual(metrics['tool_or_protocol_errors'], 2)
            self.assertEqual(metrics['failed_gateway_calls'], 1)
            self.assertEqual(metrics['tool_calls_by_name'], {'read_lines': 1})

    def test_remote_config_preparation_needs_no_key_and_never_exports_inline_credentials(self):
        remote = {'provider': 'openai-compatible', 'name': 'strong-model', 'base_url': 'https://provider.example/v1',
                  'api_key_env': 'KEEL_TEST_REMOTE_KEY'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('keel.models.CompatibleChatModel.check_credentials', side_effect=AssertionError('No key access during preparation')):
                result = prepare(root/'remote', controls(), 'sha256:'+'a'*64, 'ignored', strategy='proposal', model_config=remote)
            self.assertEqual(result['model'], 'strong-model')
            self.assertEqual(result['tasks'][0]['config']['model'], remote)
            with self.assertRaises(ValueError):
                prepare(root/'bad', controls(), 'image', 'model', model_config={**remote, 'api_key': 'never-write-this'})
            self.assertFalse((root/'bad').exists())

    def test_control_acceptance_fails_base_and_passes_minimal_reference(self):
        for spec in controls():
            with self.subTest(task=spec['id']), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'app.py'
                source = spec['files']['app.py']
                path.write_bytes(source)
                def verify():
                    return subprocess.run([sys.executable, '-B', '-c', spec['acceptance']],
                        cwd=directory, capture_output=True, timeout=10)
                self.assertEqual(verify().returncode, 1)
                path.write_bytes(source.replace(b'API_VERSION = 1', b'API_VERSION = 2'))
                self.assertEqual(verify().returncode, 0)

    def test_frozen_controls_share_behavior_and_hold_settings_fixed_across_models(self):
        specs = controls()
        self.assertEqual(len(specs), 2)
        self.assertEqual(specs[0]['acceptance'], specs[1]['acceptance'])
        self.assertGreater(len(specs[1]['files']['app.py']), len(specs[0]['files']['app.py']))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = prepare(root/'left', specs, 'sha256:'+'a'*64, 'first')
            right = prepare(root/'right', specs, 'sha256:'+'a'*64, 'second')
            for a, b in zip(left['tasks'], right['tasks']):
                self.assertEqual(a['comparison_key'], b['comparison_key'])
                self.assertEqual(a['source_sha256'], b['source_sha256'])
                self.assertEqual(a['config']['budget']['max_wallclock'], 450)
                self.assertEqual(a['config']['agent']['max_steps'], 5)
                self.assertEqual(a['config']['model']['num_ctx'], 4096)
                self.assertEqual(a['config']['model']['num_gpu'], 0)
            control = prepare(root/'control', specs, 'sha256:'+'a'*64, 'first', context_bytes=None)
            self.assertNotEqual(left['tasks'][0]['comparison_key'], control['tasks'][0]['comparison_key'])
            proposals = prepare(root/'proposals', specs, 'sha256:'+'a'*64, 'first', strategy='proposal')
            self.assertEqual(proposals['tasks'][0]['source_sha256'], left['tasks'][0]['source_sha256'])
            self.assertEqual(proposals['tasks'][0]['config']['mode'], 'proposal')
            self.assertEqual(proposals['tasks'][0]['config']['proposal']['files'], ['app.py'])
            self.assertNotEqual(proposals['tasks'][0]['comparison_key'], left['tasks'][0]['comparison_key'])
            fake_real = {**specs[0], 'id': 'starlette-1936', 'group': 'real_compatibility', 'target': 'app.py'}
            with_evidence = prepare(root/'dependency', [fake_real], 'sha256:'+'a'*64, 'first',
                strategy='proposal', dependency_evidence=True)
            request = with_evidence['tasks'][0]['config']['proposal']['dependencies'][0]
            self.assertEqual(request, {'distribution': 'anyio', 'version': '4.0.0', 'symbols': ['start_blocking_portal']})
            with self.assertRaises(FileExistsError):
                prepare(root/'left', specs, 'image', 'first')

    def test_failures_and_environment_errors_remain_in_separate_group_counts(self):
        records = [
            {'group': 'synthetic_control', 'executed': True, 'passed': True, 'status': 'completed'},
            {'group': 'synthetic_control', 'executed': True, 'passed': False, 'status': 'completed'},
            {'group': 'real_compatibility', 'executed': False, 'passed': False, 'status': 'environment_error'}]
        result = summarize(records)
        self.assertEqual(result['synthetic_control'], {'planned': 2, 'executed': 2, 'passed': 1, 'environment_errors': 0})
        self.assertEqual(result['real_compatibility'], {'planned': 1, 'executed': 0, 'passed': 0, 'environment_errors': 1})

    def test_trace_metrics_do_not_invent_compaction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'trace.jsonl'
            events = [{'event': 'llm_call_started', 'input_bytes': 1200},
                {'event': 'context_window', 'archived_turns': 0},
                {'event': 'gateway_call_started', 'tool': 'read_file'}]
            path.write_text('\n'.join(json.dumps(event) for event in events), encoding='utf-8')
            result = trace_metrics(path)
            self.assertEqual(result['archived_turns'], 0)
            self.assertEqual(result['max_model_input_bytes'], 1200)
            self.assertEqual(result['tool_calls_by_name'], {'read_file': 1})
