"""Offline action accounting; descriptive evidence, not model intent inference."""
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def analyze(directory):
    directory = Path(directory).resolve()
    result_path = directory/'results.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    trace_path = directory/'run/trace.jsonl'
    events = [json.loads(line) for line in trace_path.read_text(encoding='utf-8').splitlines()]
    roles, calls = {}, {}
    for event in events:
        role = event['role']
        row = roles.setdefault(role, {'model_calls': 0, 'protocol_errors': 0,
            'tools_requested': Counter(), 'tools_completed': Counter(),
            'tools_failed': Counter(), 'normalized_envelopes': 0, 'archived_turns': 0})
        kind = event['event']
        if kind == 'llm_call_started':
            row['model_calls'] += 1
        elif kind == 'tool_or_protocol_error':
            row['protocol_errors'] += 1
        elif kind == 'gateway_call_started':
            row['tools_requested'][event['tool']] += 1
            calls[event.get('call_id')] = (role, event['tool'])
        elif kind == 'gateway_call_finished':
            source_role, tool = calls.get(event.get('call_id'), (role, event.get('tool', '<unknown>')))
            if source_role != role:
                raise ValueError('Gateway call role mismatch')
            row['tools_completed' if event['status'] == 'completed' else 'tools_failed'][tool] += 1
        elif kind == 'action_envelope_normalized':
            row['normalized_envelopes'] += 1
        elif kind == 'context_window':
            row['archived_turns'] += event['archived_turns']
    # Exact repeated read/search actions are counted separately from cache hits.
    ledger = directory/'run/ledger.sqlite'
    with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro', uri=True)) as connection:
        actions = {}
        for role, payload in connection.execute("SELECT role,payload FROM facts WHERE summary LIKE 'Model turn %' AND kind='decision'"):
            raw = json.loads(payload)
            try:
                action = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if isinstance(action, dict) and action.get('tool') in {'list_files', 'read_file', 'read_lines', 'read_page', 'search_code'}:
                key = json.dumps(action, sort_keys=True)
                actions.setdefault(role, Counter())[key] += 1
        for role, row in roles.items():
            row['repeated_observation_requests'] = sum(n-1 for n in actions.get(role, {}).values())
    edits = sum(row['tools_requested']['replace'] for row in roles.values())
    successful_edits = sum(row['tools_completed']['replace'] for row in roles.values())
    if not result.get('executed'):
        disposition = 'model_not_executed'
    elif edits == 0:
        disposition = 'no_edit_attempt'
    elif successful_edits == 0:
        disposition = 'edit_attempts_rejected'
    elif not result.get('passed'):
        disposition = 'edited_but_trial_failed'
    else:
        disposition = 'trial_passed'
    return {'trial': str(directory), 'task_id': result.get('task_id'),
        'disposition': disposition, 'passed': result.get('passed'), 'failure': result.get('failure'),
        'budget': result.get('budget'), 'roles': roles,
        'inputs_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (result_path, trace_path, ledger)},
        'limitations': 'Offline descriptive counts only. Completed replace is a tool receipt, not proof of a correct patch. Repeated requests do not establish wasted reasoning. No new model calls or causal performance claims.'}
