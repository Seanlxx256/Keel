import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from keel.trial_diagnostics import analyze


class DiagnosticsTests(unittest.TestCase):
    def test_rejected_edits_do_not_count_as_success_and_inputs_stay_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'run').mkdir()
            (root/'results.json').write_text(json.dumps({'executed': True, 'passed': False}))
            events = [
                {'role': 'implementer', 'event': 'llm_call_started'},
                {'role': 'implementer', 'event': 'gateway_call_started', 'tool': 'replace'},
                {'role': 'implementer', 'event': 'gateway_call_finished', 'tool': 'replace', 'status': 'denied'},
                {'role': 'implementer', 'event': 'tool_or_protocol_error'},
                {'role': 'implementer', 'event': 'context_window', 'archived_turns': 2}]
            (root/'run/trace.jsonl').write_text('\n'.join(json.dumps(e) for e in events))
            ledger = root/'run/ledger.sqlite'
            with closing(sqlite3.connect(ledger)) as c:
                c.execute('CREATE TABLE facts (role TEXT, payload TEXT, summary TEXT, kind TEXT)')
                for i in range(2):
                    c.execute('INSERT INTO facts VALUES (?,?,?,?)', ('implementer',
                        json.dumps(json.dumps({'tool': 'read_page', 'arguments': {'path': 'a.py', 'start_line': 1}})), f'Model turn {i}', 'decision'))
                c.commit()
            before = ledger.read_bytes()
            report = analyze(root)
            self.assertEqual(report['disposition'], 'edit_attempts_rejected')
            role = report['roles']['implementer']
            self.assertEqual(role['repeated_observation_requests'], 1)
            self.assertEqual(role['tools_completed']['replace'], 0)
            self.assertEqual(role['archived_turns'], 2)
            self.assertEqual(before, ledger.read_bytes())
