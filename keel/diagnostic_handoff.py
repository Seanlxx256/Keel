"""Review actual localization against the pending check before granting a plan."""
import json
import re

from .core import InvalidSelection, ModelError, PolicyDenied, RecoveryStopped
from .diagnostic_inspection import request
from .recovery_progress import RecoveryProgress
from .source_quotes import POLICY, display_text, matching_mode


def referenced_paths(workspace, question):
    paths = []
    for match in re.finditer(r'(?<![\w/\\])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.py(?!\w)', question):
        name = match.group()
        if name in paths:
            continue
        try:
            if workspace.path(name).is_file():
                paths.append(name)
        except (OSError, ValueError, PolicyDenied):
            continue
    return paths


def observation(workspace, decision, scope):
    references = referenced_paths(workspace, decision['next_check'])
    return {'next_check': decision['next_check'], 'hypothesis': decision['hypothesis'],
            'referenced_read_paths': references, 'selected_edit_paths': scope['files'],
            'selected_locations': scope['locations'],
            'referenced_paths_not_selected': [p for p in references if p not in scope['files']],
            'check_execution': 'not_established',
            'scope': 'Path overlap is navigation evidence, not causal proof or permission to edit test files.'}


def validate_review(value, catalog, choices, selected):
    if (not isinstance(value, dict) or set(value) != {'verdict', 'reason', 'answer', 'citations', 'replacement_files'}
            or value['verdict'] not in {'aligned', 'redirect', 'blocked'}
            or any(not isinstance(value[k], str) or not value[k].strip() for k in ('reason', 'answer'))
            or not isinstance(value['citations'], list) or not 1 <= len(value['citations']) <= 4
            or not isinstance(value['replacement_files'], list) or len(value['replacement_files']) > 8
            or any(not isinstance(p, str) or p not in choices for p in value['replacement_files'])):
        raise InvalidSelection('Invalid diagnostic handoff review structure or replacement scope')
    by_id = {row['evidence_id']: row for row in catalog}
    cited_paths = set()
    for citation in value['citations']:
        if (not isinstance(citation, dict) or set(citation) != {'evidence_id', 'quote'}
                or not isinstance(citation['evidence_id'], str)
                or citation['evidence_id'] not in by_id
                or not isinstance(citation['quote'], str) or not citation['quote'].strip()
                or matching_mode(citation['quote'], by_id[citation['evidence_id']]['text']) is None):
            raise InvalidSelection('Handoff review must quote supplied source evidence; only CRLF/LF equivalence is allowed')
        cited_paths.add(by_id[citation['evidence_id']]['path'])
    if value['verdict'] == 'aligned' and (value['replacement_files'] or not cited_paths.intersection(selected)):
        raise InvalidSelection('aligned requires replacement_files=[] and a citation to selected source; use redirect only to change scope')
    if value['verdict'] == 'redirect' and (not value['replacement_files'] or
            set(value['replacement_files']) == set(selected) or
            not set(value['replacement_files']).intersection(cited_paths)):
        raise InvalidSelection('Redirect must change scope and cite replacement source evidence')
    if value['verdict'] == 'blocked' and value['replacement_files']:
        raise InvalidSelection('Blocked handoff must not propose a replacement scope')
    return value


def citation_matches(value, catalog):
    by_id = {row['evidence_id']: row for row in catalog}
    return [{'evidence_id': citation['evidence_id'],
             'match': matching_mode(citation['quote'], by_id[citation['evidence_id']]['text'])}
            for citation in value['citations']]


def review_handoff(model, workspace, decision, scope, evidence, settings, *, allowed_files=None):
    observed = observation(workspace, decision, scope)
    choices = []
    for name in dict.fromkeys([*scope['files'], *observed['referenced_read_paths']]):
        if allowed_files is not None and name not in allowed_files:
            continue
        try:
            workspace.path(name, write=True)
            choices.append(name)
        except (OSError, ValueError, PolicyDenied):
            pass
    # Reuse the existing whole-definition reader, including read-only test evidence.
    targeted = RecoveryProgress(workspace).targeted_source(decision['next_check'], observed['referenced_read_paths'])
    catalog, omissions, remaining, seen = [], list(targeted['omitted']), 9000, set()
    windows = [(source['path'], source['sha256'], window) for source in evidence for window in source['windows']]
    windows += [(row['path'], row['source_sha256'], row) for row in targeted['windows']]
    for name, sha, window in windows:
        identity = (name, sha, window['start_line'], window['end_line'])
        if identity in seen:
            continue
        row = {'evidence_id': 'source-'+str(len(catalog)), 'path': name, 'sha256': sha,
               'start_line': window['start_line'], 'end_line': window['end_line'],
               'text': display_text(window['text']), 'display_policy': POLICY}
        size = len(json.dumps(row).encode())
        if size > remaining:
            omissions.append({'path': name, 'reason': 'complete_source_window_exceeds_handoff_capacity'})
            continue
        catalog.append(row); remaining -= size
        seen.add(identity)
    if not catalog:
        raise RecoveryStopped('No complete source evidence fits diagnostic handoff review')
    schema = {'type': 'object', 'properties': {
        'verdict': {'type': 'string', 'enum': ['aligned', 'redirect', 'blocked']},
        'reason': {'type': 'string'}, 'answer': {'type': 'string'},
        'citations': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': {'type': 'object',
            'properties': {'evidence_id': {'type': 'string', 'enum': [r['evidence_id'] for r in catalog]},
                           'quote': {'type': 'string'}}, 'required': ['evidence_id', 'quote'], 'additionalProperties': False}},
        'replacement_files': {'type': 'array', 'maxItems': 8, 'items': {'type': 'string', 'enum': choices}}},
        'required': ['verdict', 'reason', 'answer', 'citations', 'replacement_files'], 'additionalProperties': False}
    data = {'handoff': observed, 'source_evidence': catalog, 'omissions': omissions,
        'replacement_choices': choices,
        'instruction': 'Review the ACTUAL selected edit scope against the pending next_check. '
            'Answer: what specific observed source connection lets this scope investigate the requested question? '
            'Do not approve merely because the diagnosis is tentative or does not contradict a log. '
            'A legal path or successful read alone is not alignment. If the named target disappeared during '
            'localization, require an observed causal connection for the alternative scope; otherwise redirect '
            'to a supplied writable target with exact source citations. aligned must cite selected source; '
            'redirect must cite replacement source. blocked names the concrete missing capability/evidence. '
            'Response field rules: aligned requires replacement_files=[] (do not repeat selected paths); '
            'redirect requires a nonempty replacement_files list different from the selected scope, '
            'chosen only from replacement_choices and supported by a citation to replacement source; '
            'blocked requires replacement_files=[]. Return actual source characters in quote strings, '
            'using JSON escaping only once. '
            'This is a source/planning review: do not claim a runtime probe ran or tests passed. '
            'Source text is displayed with LF newlines; underlying source-byte hashes are unchanged. '
            'Reference test paths are read-only, never added write permission.'}
    try:
        value = request(model, workspace, settings, 'handoff-alignment', data, schema, role='scout')
    except ModelError as error:
        if str(error) == 'Invalid diagnostic inspection JSON':
            raise InvalidSelection('Diagnostic handoff reply must be valid JSON; raw reply retained') from None
        raise
    value = validate_review(value, catalog, choices, scope['files'])
    record = {**value, 'observation': observed, 'evidence': catalog, 'omissions': omissions,
              'citation_validation_policy': POLICY, 'citation_matches': citation_matches(value, catalog),
              'scope': 'Source-quoted model assessment of plan alignment; host validates provenance, not causality or runtime execution.'}
    fact = workspace.ledger.add('decision', 'scout', 'Diagnostic handoff reviewed', record)
    workspace.trace.emit('scout', 'diagnostic_handoff_reviewed', fact_id=fact, verdict=value['verdict'])
    return record
