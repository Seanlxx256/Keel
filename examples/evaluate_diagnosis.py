"""Paired synthetic diagnosis evaluation, separate from the production repair loop."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.core import Budget, Limits, ModelError
from keel.execution import CommandRunner
from keel.models import from_config


GUIDANCE = {
    'baseline': 'Diagnose the failure using the available checks and observations. Return the requested JSON.',
    'candidate': 'Diagnose the failure using the available checks and observations. '
    'Before checking, predict the result under each hypothesis. Prefer a check whose predictions differ. '
    'After observing the result, explicitly reject an incompatible hypothesis; do not repeat an '
    'unchanged check. Cite only observations actually received. If evidence cannot distinguish '
    'the causes, conclude undetermined rather than guessing. Return the requested JSON.',
}
FAMILIES = {
    'reader': {
        'symptom': 'read_value(" 7 ") returns 0; expected 7.',
        'hypotheses': {
            'A': 'The cache always returns 0; decoding itself accepts surrounding spaces.',
            'B': 'The cache is disabled; decoding rejects surrounding spaces and returns 0.',
        },
        'sources': {
            'A': 'def decode(raw):\n    return int(raw.strip())\n'
                 'def read_value(raw):\n    return 0\n',
            'B': 'def decode(raw):\n    return int(raw) if raw.isdecimal() else 0\n'
                 'def read_value(raw):\n    return decode(raw)\n',
        },
        'probes': {
            'decode_spaced': 'decode(" 7 ") == 7',
            'read_spaced': 'read_value(" 7 ") == 7',
            'zero_control': 'read_value("0") == 0',
        },
    },
    'counter': {
        'symptom': 'count_positive([0, 1]) returns 2; expected 1.',
        'hypotheses': {
            'A': 'Selection incorrectly includes zero; aggregation correctly counts selected items.',
            'B': 'Selection correctly excludes zero; aggregation adds one extra item.',
        },
        'sources': {
            'A': 'def select(xs):\n    return [x for x in xs if x >= 0]\n'
                 'def aggregate(xs):\n    return len(xs)\n'
                 'def count_positive(xs):\n    return aggregate(select(xs))\n',
            'B': 'def select(xs):\n    return [x for x in xs if x > 0]\n'
                 'def aggregate(xs):\n    return len(xs) + 1\n'
                 'def count_positive(xs):\n    return aggregate(select(xs))\n',
        },
        'probes': {
            'select_zero': 'select([0]) == []',
            'aggregate_one': 'aggregate([1]) == 1',
            'original_failure': 'count_positive([0, 1]) == 1',
        },
    },
}
# Both causes occur with identical initial symptoms. Labels are frozen, not model-dependent.
CASES = [('case-1', 'reader', 'A'), ('case-2', 'counter', 'B'),
         ('case-3', 'reader', 'B'), ('case-4', 'counter', 'A')]
SCHEMA = {'type': 'object', 'properties': {
    'action': {'type': 'string', 'enum': ['probe', 'conclude']},
    'probe_id': {'type': 'string'},
    'predicted_A': {'type': 'boolean'}, 'predicted_B': {'type': 'boolean'},
    'conclusion': {'type': 'string', 'enum': ['A', 'B', 'undetermined']},
    'evidence_ids': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 3},
    'reason': {'type': 'string', 'maxLength': 1200}},
    'required': ['action', 'probe_id', 'predicted_A', 'predicted_B', 'conclusion', 'evidence_ids', 'reason'],
    'additionalProperties': False}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def run_probe(family, cause, probe_id, timeout=5):
    """Only versioned fixture code executes, never model-provided commands or expressions."""
    expression = family['probes'][probe_id]
    with tempfile.TemporaryDirectory(prefix='keel-diagnosis-') as temporary:
        root = Path(temporary)
        (root/'probe.py').write_bytes((family['sources'][cause]
            + '\nimport json\nprint(json.dumps(bool(' + expression + ')))\n').encode())
        result = CommandRunner().run([sys.executable, '-I', '-B', 'probe.py'], root, timeout)
    if result['returncode'] != 0 or result['timeout']:
        raise RuntimeError('Fixed diagnostic probe failed to execute')
    value = json.loads(result['stdout'])
    if type(value) is not bool:
        raise ValueError('Probe result must be boolean')
    return value


def validate_response(value, probe_ids, known_ids):
    if (not isinstance(value, dict) or set(value) != set(SCHEMA['required'])
            or value['action'] not in ('probe', 'conclude')
            or value['conclusion'] not in ('A', 'B', 'undetermined')
            or type(value['predicted_A']) is not bool or type(value['predicted_B']) is not bool
            or not isinstance(value['reason'], str) or not 1 <= len(value['reason']) <= 1200
            or not isinstance(value['evidence_ids'], list) or len(value['evidence_ids']) > 3
            or any(not isinstance(x, str) or x not in known_ids for x in value['evidence_ids'])):
        raise ValueError('Invalid diagnostic response or fabricated evidence citation')
    if value['action'] == 'probe' and value['probe_id'] not in probe_ids:
        raise ValueError('Unknown probe; model commands cannot execute')
    if value['action'] == 'conclude' and value['probe_id'] != '':
        raise ValueError('Conclude must use an empty probe_id')


def score_trial(cause, observations, final):
    cited = set(final['evidence_ids']) if final else set()
    # Check predictions against independently executed counterfactual fixtures.
    informative = [o for o in observations if o['oracle_A'] != o['oracle_B']]
    valid = [o for o in informative if o['predicted_A'] == o['oracle_A']
             and o['predicted_B'] == o['oracle_B']]
    grounded = any(o['id'] in cited for o in valid)
    correct = bool(final and final['conclusion'] == cause)
    return {'correct_conclusion': correct, 'discriminating_probe': bool(informative),
            'correct_counterfactual_predictions': bool(valid), 'cited_valid_probe': grounded,
            'passed': correct and grounded,
            'scope': 'Objective probe/prediction/citation checks; prose rationale is not automatically verified.'}


def trial(model, family, cause, arm, output, deadline, *, guidance=None, budget=None, max_output=512, protocol_extra="", recover_guards=False):
    budget = budget if budget is not None else Budget(Limits(
        max_model_calls=3, max_tokens=16000, max_tool_calls=6, max_wallclock=150))
    public = {'symptom': family['symptom'], 'hypotheses': family['hypotheses'],
              'available_probes': family['probes'],
              'protocol': 'At most 3 model turns, at most 2 distinct probes. '
              'A probe executes the displayed boolean expression in the hidden current fixture. '
              'State predictions for both hypotheses before seeing a result. '
              'For conclude use empty probe_id and cite observation IDs; prediction fields are ignored. '
              'The initial symptom alone does not distinguish the two hypotheses.'}
    if protocol_extra:
        public['evidence_contract'] = protocol_extra
    messages = [{'role': 'system', 'content': GUIDANCE[arm] if guidance is None else guidance},
                {'role': 'user', 'content': json.dumps(public)}]
    observations = []; seen = set(); final = None
    record = {'status': 'running', 'steps': []}
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output/'trial.json', record)
    try:
        for step in range(3):
            remaining = min(budget.remaining, deadline - time.monotonic(), 45)
            if remaining <= 0:
                raise TimeoutError('Diagnostic evaluation time budget exhausted')
            budget.allow_model(len(json.dumps(messages).encode()), max_output)
            # Persist the charged attempt before dispatch, so interruption cannot hide a paid call.
            record['budget'] = budget.report()
            record['pending_call'] = step + 1
            atomic_json(output/'trial.json', record)
            print(f'[Diagnosis] {output.name} step {step + 1}/3', flush=True)
            try:
                reply = model.complete_json(messages, schema=SCHEMA, timeout=remaining, max_output=max_output)
            except ModelError as error:
                if error.tokens is not None:
                    budget.charge_tokens(error.tokens)
                raise
            budget.charge_tokens(reply.tokens if reply.tokens is not None else
                                 len(json.dumps(messages).encode()) + len(reply.content.encode()))
            atomic_json(output/f'reply-{step + 1}.json', {
                'content': reply.content, 'tokens': reply.tokens, 'metadata': reply.metadata})
            value = None
            try:
                value = json.loads(reply.content)
                record['steps'].append(value)
                validate_response(value, family['probes'], {o['id'] for o in observations})
            except (ValueError, TypeError):
                from keel.guard_recovery import citation_incident
                incident = citation_incident(value, {o['id'] for o in observations}) if recover_guards else None
                # Recovery is only for the reference: all other action fields must already be valid.
                if incident is not None:
                    try:
                        validate_response({**value, 'evidence_ids': []}, family['probes'], set())
                    except (ValueError, TypeError):
                        incident = None
                if incident is not None:
                    event = incident.record()
                    can_retry = (not record.get('guard_events') and step < 2
                                 and budget.model_calls < budget.limits.max_model_calls
                                 and budget.remaining > 0 and deadline > time.monotonic())
                    event.update(disposition='request_new_action' if can_retry else 'checkpoint_stop',
                                 remaining_turns=2-step, budget=budget.report())
                    record.setdefault('guard_events', []).append(event)
                    record.pop('pending_call', None)
                    atomic_json(output/'trial.json', record)
                    if can_retry:
                        messages.extend([{'role': 'assistant', 'content': reply.content},
                                         {'role': 'user', 'content': json.dumps({'guard': event})}])
                        continue
                record['protocol_failure'] = 'Invalid response or fabricated evidence citation'
                break
            if value['action'] == 'conclude':
                final = value
                break
            probe = value['probe_id']
            if probe in seen or len(seen) >= 2:
                record['protocol_failure'] = 'Repeated probe or probe limit exceeded'
                break
            seen.add(probe)
            outcomes = {}
            for variant in ('A', 'B'):
                budget.charge_tool()
                outcomes[variant] = run_probe(family, variant, probe,
                    timeout=max(.01, min(5, budget.remaining, deadline-time.monotonic())))
            observation = {'id': f'observation-{len(observations)+1}', 'probe_id': probe,
                           'result': outcomes[cause], 'oracle_A': outcomes['A'], 'oracle_B': outcomes['B'],
                           'predicted_A': value['predicted_A'], 'predicted_B': value['predicted_B']}
            observations.append(observation)
            messages.extend([{'role': 'assistant', 'content': reply.content},
                {'role': 'user', 'content': json.dumps({
                    'observation': {k: observation[k] for k in ('id', 'probe_id', 'result')},
                    'turns_remaining': 2-step})}])
            record['observations'] = observations
            record.pop('pending_call', None)
            atomic_json(output/'trial.json', record)
        record.update(status='completed', final=final, observations=observations,
                      score=score_trial(cause, observations, final))
        record.pop('pending_call', None)
    except Exception as error:
        record.update(status='incomplete', error_type=type(error).__name__)
        raise
    finally:
        record['budget'] = budget.report()
        atomic_json(output/'trial.json', record)
        if record['status'] == 'completed':
            atomic_json(output/'receipt.json', {
                'trial_sha256': hashlib.sha256((output/'trial.json').read_bytes()).hexdigest()})
    return record


def load_completed(output):
    raw = (output/'trial.json').read_bytes()
    receipt = json.loads((output/'receipt.json').read_text(encoding='utf-8'))
    if receipt['trial_sha256'] != hashlib.sha256(raw).hexdigest():
        raise ValueError('Completed arm receipt mismatch')
    record = json.loads(raw)
    if record['status'] != 'completed':
        raise ValueError('Incomplete arm retained; automatic paid retry is disabled')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-config', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    config_bytes = args.model_config.read_bytes() if args.model_config else b''
    manifest = {'implementation_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'fixtures_sha256': digest([FAMILIES, CASES]), 'guidance': GUIDANCE,
                'model_config_sha256': hashlib.sha256(config_bytes).hexdigest(),
                'python': sys.version, 'executable': sys.executable,
                'limits': {'max_model_calls': 24, 'max_tokens': 128000, 'wallclock_per_invocation': 1200}}
    model = None
    if args.execute:
        if not config_bytes:
            parser.error('--execute requires --model-config')
        model = from_config(json.loads(config_bytes))
        if hasattr(model, 'check_credentials'):
            model.check_credentials()
    if args.resume:
        saved = json.loads((args.output/'manifest.json').read_text(encoding='utf-8'))
        if manifest != saved:
            raise ValueError('Resume input/implementation mismatch; preserve old results and use a new output')
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        atomic_json(args.output/'manifest.json', manifest)
    report = {'status': 'prepared', 'records': [], 'manifest_sha256': digest(manifest),
              'scope': 'Four synthetic cases in two paired families; diagnosis only, not repair or benchmark efficacy.'}
    deadline = time.monotonic() + 1200
    try:
        if model:
            for index, (case_id, family_id, cause) in enumerate(CASES):
                arms = ('baseline', 'candidate') if index % 2 == 0 else ('candidate', 'baseline')
                for arm in arms:
                    output = args.output/f'{case_id}-{arm}'
                    if output.exists():
                        if not args.resume:
                            raise ValueError('Existing arm cannot be overwritten')
                        saved = load_completed(output)
                        print(f'[Diagnosis] reuse {output.name}', flush=True)
                        record = saved
                    else:
                        record = trial(model, FAMILIES[family_id], cause, arm, output, deadline)
                    report['records'].append({'case': case_id, 'arm': arm, 'score': record['score'],
                                              'budget': record['budget']})
                    atomic_json(args.output/'report.json', report)
            report['status'] = 'completed'
            report['summary'] = {arm: {
                'passed': sum(r['score']['passed'] for r in report['records'] if r['arm'] == arm),
                'cases': 4} for arm in ('baseline', 'candidate')}
    except Exception as error:
        report.update(status='incomplete', error_type=type(error).__name__)
        raise
    finally:
        atomic_json(args.output/'report.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
