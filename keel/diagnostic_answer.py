"""Evidence-backed source answers before diagnostic patch proposals.

Host checks provenance and protocol, not semantic truth or execution of a probe.
"""
import hashlib

from .source_quotes import matching_mode
from .core import RecoveryStopped


class DiagnosticEvidenceNeeded(RecoveryStopped):
    def __init__(self, answer):
        super().__init__('Diagnostic question unresolved: ' + answer['missing_evidence'])
        self.answer = answer


def merge_evidence(*groups):
    sources = {}
    for group in groups:
        for row in group:
            previous = sources.get(row['path'])
            if previous is not None:
                if previous['sha256'] != row['sha256']:
                    raise ValueError('Conflicting diagnostic source versions')
                previous['windows'].extend(row['windows'])
            else:
                sources[row['path']] = {**row, 'windows': list(row['windows'])}
    return list(sources.values())


def schema():
    return {'type': 'object', 'properties': {
        'question': {'type': 'string'},
        'status': {'type': 'string', 'enum': ['source_answer', 'unknown']},
        'answer': {'type': 'string'},
        'hypothesis_update': {'type': 'string', 'enum': ['supported', 'refuted', 'undetermined']},
        'missing_evidence': {'type': 'string'},
        'citations': {'type': 'array', 'maxItems': 4, 'items': {
            'type': 'object', 'properties': {k: {'type': 'string'} for k in ('path', 'sha256', 'quote')},
            'required': ['path', 'sha256', 'quote'], 'additionalProperties': False}}},
        'required': ['question', 'status', 'answer', 'hypothesis_update', 'missing_evidence', 'citations'],
        'additionalProperties': False}


INSTRUCTION = (
    'Before proposing a diagnostic repair, answer diagnostic_check.next_check explicitly in diagnostic_answer. '
    'Copy the exact question. Use only supplied current source windows and quote them with path and sha256. '
    'A relevant file or a planned inspection is not an answer. Explain what was learned and whether it '
    'supports, refutes or leaves the hypothesis undetermined. You have no execution tool: never claim '
    'a runtime probe ran. If source cannot answer the question or an execution observation is required, '
    'return status=unknown, hypothesis_update=undetermined, specific missing_evidence and edits=[]. '
    'source_answer requires at least one exact source citation, missing_evidence="", and a concrete '
    'reason why the edits address the answered question. Do not submit comment-only changes as a repair. '
    'A source_answer is an unverified model interpretation, not a confirmed root cause or test pass.'
)


def validate(value, check, evidence, workspace):
    if not isinstance(value, dict) or set(value) != set(schema()['required']):
        raise ValueError('diagnostic_answer requires every declared field')
    if any(not isinstance(value[k], str) for k in ('question', 'status', 'answer', 'hypothesis_update', 'missing_evidence')):
        raise ValueError('Diagnostic answer fields must be strings')
    if value['question'] != check['next_check'] or not value['answer'].strip():
        raise ValueError('Answer the exact pending diagnostic question, not a new plan')
    if value['status'] not in ('source_answer', 'unknown') or value['hypothesis_update'] not in ('supported', 'refuted', 'undetermined'):
        raise ValueError('Invalid diagnostic answer status or hypothesis update')
    citations = value['citations']
    if not isinstance(citations, list) or len(citations) > 4:
        raise ValueError('Diagnostic answer requires 0..4 source citations')
    sources = {row['path']: row for row in evidence}
    for citation in citations:
        if not isinstance(citation, dict) or set(citation) != {'path', 'sha256', 'quote'}:
            raise ValueError('Diagnostic citation requires path, sha256 and quote')
        if any(not isinstance(citation[k], str) for k in citation):
            raise ValueError('Diagnostic citation fields must be strings')
        source = sources.get(citation['path'])
        if source is None or citation['sha256'] != source['sha256']:
            raise ValueError('Diagnostic citation must reference supplied current evidence')
        current = workspace.read(citation['path'], role='implementer')['value']
        if hashlib.sha256(current.encode()).hexdigest() != source['sha256']:
            raise ValueError('Diagnostic citation source changed since evidence collection')
        if not any(matching_mode(citation['quote'], w['text']) for w in source['windows']):
            raise ValueError('Diagnostic citation must quote a supplied source window')
    if value['status'] == 'unknown':
        if not value['missing_evidence'].strip() or value['hypothesis_update'] != 'undetermined':
            raise ValueError('Unknown requires specific missing evidence and undetermined hypothesis')
    elif not citations or value['missing_evidence']:
        raise ValueError('source_answer requires citations and empty missing_evidence')
    return {**value, 'basis': 'source_only', 'check_execution': 'not_established',
            'scope': 'Host validates provenance, not the truth or sufficiency of the model answer.'}


def validate_response(proposal, check, evidence, workspace):
    """Shared envelope/answer checks; patch validity is checked separately."""
    if (not isinstance(proposal, dict) or set(proposal) != {'edits', 'summary', 'diagnostic_answer'}
            or not isinstance(proposal['summary'], str) or not isinstance(proposal['edits'], list)
            or len(proposal['edits']) > 8):
        raise ValueError('Diagnostic proposal requires edits, summary and diagnostic_answer')
    answer = validate(proposal['diagnostic_answer'], check, evidence, workspace)
    if answer['status'] == 'unknown' and proposal['edits'] != []:
        raise ValueError('Unknown diagnostic answer requires edits=[]; no speculative patch')
    if answer['status'] == 'source_answer' and not proposal['edits']:
        raise ValueError('source_answer proposal requires at least one edit')
    return answer
