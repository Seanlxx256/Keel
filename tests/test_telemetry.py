import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keel.core import Trace
from keel.runtime import run
from keel.telemetry import LocalTelemetry


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def spans(self, path):
        return json.loads(path.read_text())['resourceSpans'][0]['scopeSpans'][0]['spans']

    def test_nested_calls_share_trace_and_do_not_export_source_or_commands(self):
        telemetry = LocalTelemetry(self.root / 'spans.json')
        trace = Trace(self.root / 'trace.jsonl', telemetry)
        for role, event, data in [
            ('runtime', 'run_started', {'goal': 'secret-goal'}),
            ('scout', 'role_entered', {'phase': 'main'}),
            ('scout', 'llm_call_started', {'step': 0, 'input_bytes': 200}),
            ('scout', 'llm_call_finished', {'tokens': 12}),
            ('scout', 'gateway_call_started', {'call_id': 'abc', 'tool': 'read_file', 'transport': 'local'}),
            ('scout', 'gateway_call_finished', {'call_id': 'abc', 'status': 'denied', 'error_type': 'PolicyDenied'}),
            ('scout', 'role_exited', {'status': 'failed'}),
            ('runtime', 'run_finished', {'status': 'failed'}),
        ]:
            trace.emit(role, event, **data)
        spans = self.spans(telemetry.path)
        self.assertEqual(len(spans), 4)
        root, role, model, tool = spans
        self.assertEqual(role['parentSpanId'], root['spanId'])
        self.assertEqual(model['parentSpanId'], role['spanId'])
        self.assertEqual(tool['parentSpanId'], role['spanId'])
        self.assertEqual(tool['status']['code'], 2)
        for span in spans:
            self.assertRegex(span['traceId'], r'^[0-9a-f]{32}$')
            self.assertRegex(span['spanId'], r'^[0-9a-f]{16}$')
            self.assertEqual(span['traceId'], root['traceId'])
            self.assertGreaterEqual(int(span['endTimeUnixNano']), int(span['startTimeUnixNano']))
        self.assertNotIn('secret-goal', telemetry.path.read_text())
        events = [json.loads(line) for line in trace.path.read_text().splitlines()]
        self.assertEqual(events[2]['span_id'], events[3]['span_id'])

    def test_runtime_failure_closes_interrupted_verification(self):
        (self.root / 'app.py').write_text('VERSION = 1\n')
        config = {'goal': 'Verify', 'acceptance': [[sys.executable, '-c', 'pass']], 'work_items': []}
        output = self.root / '.keel' / 'run'
        with patch('keel.execution.CommandRunner.run', side_effect=RuntimeError('private-command-data')):
            with self.assertRaises(RuntimeError):
                run(config, self.root, output)
        result = json.loads((output / 'result.json').read_text())
        self.assertTrue(result['telemetry']['exported'])
        spans = self.spans(output / 'spans.otlp.json')
        verifier = next(s for s in spans if s['name'] == 'keel.verification')
        self.assertEqual(verifier['status']['code'], 2)
        self.assertTrue(all('endTimeUnixNano' in s for s in spans))
        self.assertNotIn('private-command-data', (output / 'spans.otlp.json').read_text())

    def test_export_failure_is_visible_without_changing_task_outcome(self):
        telemetry = LocalTelemetry(self.root / 'missing' / 'spans.json')
        trace = Trace(self.root / 'trace.jsonl', telemetry)
        trace.emit('runtime', 'run_started')
        trace.emit('runtime', 'run_finished', status='passed')
        self.assertFalse(telemetry.report()['exported'])
        self.assertEqual(telemetry.report()['export_error'], 'FileNotFoundError')
        self.assertEqual(telemetry.spans[0]['status']['code'], 1)
