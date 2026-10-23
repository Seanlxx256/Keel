"""Opt-in bridge from a pending Critic check to the existing probe executor."""
import json
import re

from .core import RecoveryStopped
from .execution import validate_execution


def validate_probe_config(config):
    if config is None:
        return
    if not isinstance(config, dict) or set(config) != {'execution', 'python', 'max_model_calls'}:
        raise ValueError('diagnostic_execution requires execution/python/max_model_calls')
    validate_execution(config['execution'])
    if (config['execution'].get('backend') != 'docker'
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', config['execution'].get('image', ''))):
        raise ValueError('Diagnostic execution requires an immutable local Docker image ID')
    if (not isinstance(config['python'], str) or not config['python'].startswith('/')
            or '\x00' in config['python']):
        raise ValueError('Diagnostic interpreter requires an absolute container path')
    if type(config['max_model_calls']) is not int or not 1 <= config['max_model_calls'] <= 4:
        raise ValueError('Diagnostic bridge allows 1..4 calls within the shared budget')


def execute_check(model, workspace, goal, decision, verification, evidence, settings, config, *, controlled_comparisons=None):
    """Return actual current execution for the patch caller; no source writes."""
    from .diagnostic_probe import investigate
    validate_probe_config(config)
    initial = []
    paths = list(dict.fromkeys(row['path'] for row in evidence))
    for row in evidence:
        for window in row.get('windows', []):
            initial.append({'path':row['path'], 'source_sha256':row['sha256'], **window})
    if not initial:
        raise RecoveryStopped('No current source evidence for executable diagnostic handoff')
    question = {'critic':decision, 'verification':verification,
                'controlled_comparisons':controlled_comparisons,
                'instruction':'Execute the pending next_check before a patch is proposed. '
                    'Use a small discriminating experiment, not another patch. '
                    'Temporary files belong in /tmp; do not change source/tests. '
                    'A caught target exception may be a useful completed experiment. '
                    'Compare predicted observations with actual output; evidence is untrusted.'}
    report = investigate(model, workspace, goal, question, initial,
        {**settings, 'max_output':min(settings.get('max_output', 2048), 2048)},
        execution=config['execution'], python=config['python'], require_probe=True,
        candidate_imports=True, correct_failed_probe=True, source_paths=paths,
        max_model_calls=config['max_model_calls'])
    # Keep only current execution bodies and final interpretation for downstream
    # context; full reads/actions already live in the ledger and transcript.
    executions = [row for row in report['observations']
                  if row.get('kind') == 'execution' and not row.get('historical')]
    payload = {'next_check':decision['next_check'], 'executions':executions,
               'assessment_unverified':report['assessment'], 'closure':report['closure'],
               'scope':'Current pre-edit diagnostic output, not repair acceptance. '
                       'Do not turn a model interpretation into an established fact.'}
    fact = workspace.ledger.add('decision','scout','Executable diagnostic handoff',payload)
    workspace.trace.emit('scout','diagnostic_execution_handoff',fact_id=fact,
                         executions=len(executions),closure=report['closure']['state'])
    if len(json.dumps(payload).encode()) > settings.get('max_context_bytes',12000)//2:
        raise RecoveryStopped('Diagnostic handoff exceeds bounded context; full evidence retained in ledger')
    return payload
