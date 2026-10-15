import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

from examples.run_agent_baseline import controls, prepare, summarize, trace_metrics


class AgentBaselineTests(unittest.TestCase):
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
            fake_real = {**specs[0], 'id': 'real-fixture', 'group': 'real_compatibility', 'target': 'app.py'}
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
