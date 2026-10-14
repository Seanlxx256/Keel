"""Local OTLP/JSON trace-file export for Keel's sequential runtime."""
from __future__ import annotations

import json
import secrets
import time


def attributes(values):
    result = []
    for key, value in values.items():
        if value is None:
            continue
        kind = 'boolValue' if type(value) is bool else 'intValue' if type(value) is int else 'stringValue'
        result.append({'key': 'keel.' + key, 'value': {kind: str(value) if kind == 'intValue' else value}})
    return result


class LocalTelemetry:
    def __init__(self, path):
        self.path = path
        self.trace_id = secrets.token_hex(16)
        self.spans, self.active = [], {}
        self.role = None
        self.wall, self.monotonic = time.time_ns(), time.monotonic_ns()
        self.export_error = None
        self.exported = False

    def now(self):
        return self.wall + time.monotonic_ns() - self.monotonic

    def start(self, key, name, parent=None, **data):
        span = {'traceId': self.trace_id, 'spanId': secrets.token_hex(8), 'name': name,
                'kind': 1, 'flags': 1, 'startTimeUnixNano': str(self.now()), 'attributes': attributes(data)}
        if parent:
            span['parentSpanId'] = parent['spanId']
        self.spans.append(span)
        self.active[key] = span
        return span

    def end(self, key, failed=False, **data):
        span = self.active.pop(key, None)
        if span:
            span['endTimeUnixNano'] = str(self.now())
            span['status'] = {'code': 2 if failed else 1}
            span['attributes'].extend(attributes(data))
        return span

    def observe(self, record):
        event, role = record['event'], record['role']
        root = self.active.get('run')
        current = self.active.get('role', root)
        operations = [value for key, value in self.active.items() if key not in {'run', 'role'}]
        span = operations[-1] if operations else current
        if event == 'run_started':
            span = self.start('run', 'keel.run')
        elif event == 'role_entered':
            span = self.start('role', 'keel.role.' + role, root, role=role, phase=record.get('phase'))
            self.role = role
        elif event == 'role_exited':
            # An exception can leave a model or verifier start without its finish event.
            for key in list(self.active):
                if key not in {'run', 'role'}:
                    self.end(key, True, interrupted=True)
            span = self.end('role', record.get('status') == 'failed')
            self.role = None
        elif event in {'llm_call_started', 'gateway_call_started', 'command_started'}:
            kind = {'llm_call_started': 'model', 'gateway_call_started': 'tool', 'command_started': 'verification'}[event]
            key = record.get('call_id', kind)
            span = self.start(key, 'keel.' + kind, current, role=role,
                              tool=record.get('tool'), transport=record.get('transport'),
                              phase=record.get('phase'), step=record.get('step'),
                              input_bytes=record.get('input_bytes'))
        elif event in {'llm_call_finished', 'gateway_call_finished', 'command_finished'}:
            key = record.get('call_id', 'model' if event == 'llm_call_finished' else 'verification')
            span = self.end(key, record.get('status') in {'failed', 'denied'} or
                            record.get('returncode', 0) != 0 or record.get('timeout', False),
                            tokens=record.get('tokens'), fact_id=record.get('fact_id'),
                            returncode=record.get('returncode'), error_type=record.get('error_type'))
        elif event == 'run_finished':
            for key in list(self.active):
                if key != 'run':
                    self.end(key, True, interrupted=True)
            span = self.end('run', record.get('status') != 'passed', outcome=record.get('status'))
            self.export()
        if span:
            record.update(trace_id=self.trace_id, span_id=span['spanId'], trace_flags='01')
        elif root:
            record.update(trace_id=self.trace_id, span_id=root['spanId'], trace_flags='01')

    def export(self):
        payload = {'resourceSpans': [{'resource': {'attributes': [
            {'key': 'service.name', 'value': {'stringValue': 'keel'}}]},
            'scopeSpans': [{'scope': {'name': 'keel.runtime'}, 'spans': self.spans}]}]}
        try:
            self.path.write_text(json.dumps(payload, separators=(',', ':')) + '\n', encoding='utf-8')
            self.exported = True
        except OSError as error:
            self.export_error = type(error).__name__

    def report(self):
        return {'format': 'otlp-json', 'trace_id': self.trace_id, 'spans': len(self.spans),
                'exported': self.exported, 'export_error': self.export_error, 'path': str(self.path)}
