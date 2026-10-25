"""Offline prompt-candidate selection; never installs a production policy."""
import json
import time
from pathlib import Path

from compass.progress import atomic_json
from keel.core import Budget, Limits, ModelError
from examples.evaluate_diagnosis import CASES, FAMILIES, GUIDANCE, digest, trial, load_completed

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['candidates'],
          'properties': {'candidates': {'type': 'array', 'maxItems': 3, 'items': {
              'type': 'object', 'additionalProperties': False,
              'required': ['id', 'guidance'], 'properties': {
                  'id': {'type': 'string', 'pattern': '^[a-z][a-z0-9_]{0,63}$'},
                  'guidance': {'type': 'string', 'minLength': 1, 'maxLength': 2000}}}}}}


def validate_candidates(value):
    import re
    if not isinstance(value, dict) or set(value) != {'candidates'}:
        raise ValueError('Only prompt candidates are allowed')
    candidates = value['candidates']
    if not isinstance(candidates, list) or len(candidates) > 3:
        raise ValueError('At most three candidates')
    seen = {'incumbent'}
    for candidate in candidates:
        if (not isinstance(candidate, dict) or set(candidate) != {'id', 'guidance'}
                or not isinstance(candidate['id'], str)
                or not re.fullmatch('[a-z][a-z0-9_]{0,63}', candidate['id'])
                or candidate['id'] in seen
                or not isinstance(candidate['guidance'], str)
                or not 1 <= len(candidate['guidance']) <= 2000):
            raise ValueError('Invalid or duplicate prompt candidate')
        seen.add(candidate['id'])
    return candidates


def select(records, candidates, *, cases=CASES):
    """All cases required; strict improvement with no per-case regression."""
    expected = {case[0] for case in cases}
    by_arm = {}
    for record in records:
        arm = by_arm.setdefault(record['arm'], {})
        if record['case'] in arm or record['case'] not in expected:
            raise ValueError('Duplicate or unknown case')
        arm[record['case']] = record['passed']
    arms = ['incumbent'] + [c['id'] for c in candidates]
    if set(by_arm) != set(arms) or any(set(by_arm[a]) != expected for a in arms):
        raise ValueError('Incomplete comparison cannot select a winner')
    baseline = by_arm['incumbent']
    eligible = [a for a in arms[1:] if all(not baseline[c] or by_arm[a][c] for c in expected)
                and sum(by_arm[a].values()) > sum(baseline.values())]
    winner = max(eligible, key=lambda a: sum(by_arm[a].values())) if eligible else 'incumbent'
    return {'retained': winner, 'rejected': [a for a in arms[1:] if a != winner],
            'eligible_tied_best': [a for a in eligible if sum(by_arm[a].values()) == sum(by_arm[winner].values())],
            'production_promoted': False, 'independent_validation_required': True,
            'scope': 'Exposed synthetic development cases; provisional prompt selection only.'}


def execute(model, output, *, config_hash, max_seconds=900, resume=False, validation=None, feedback=None, reuse_proposal=None, recover_guards=False):
    if feedback is not None and not 0 < max_seconds <= 300:
        raise ValueError('Feedback replay time budget must be <=300 seconds')
    families, cases = FAMILIES, CASES
    protocol_extra = ''
    if validation is not None and feedback is not None:
        raise ValueError('Choose frozen validation or feedback proposal, not both')
    if validation is not None or feedback is not None:
        from keel.outer_validation_cases import FAMILIES_V2, CASES_V2, EVIDENCE_PROTOCOL
        families = FAMILIES_V2
        cases = [(f'repeat-{repeat}-{name}', family, cause)
                 for repeat in (1, 2) for name, family, cause in CASES_V2]
        protocol_extra = EVIDENCE_PROTOCOL
        if feedback is not None:
            cases = feedback['cases']
    output = Path(output)
    output.mkdir(parents=True, exist_ok=resume)
    budget = Budget(Limits(max_wallclock=max_seconds, max_model_calls=19 if feedback is not None else (120 if validation is not None else 49),
                           max_tokens=260000, max_tool_calls=24 if feedback is not None else (160 if validation is not None else 96)))
    root = Path(__file__).resolve().parents[1]
    manifest = {'config_sha256': config_hash, 'fixture_sha256': digest([families, cases]),
                'validation': validation, 'feedback': feedback, 'recover_guards': recover_guards, 'evidence_contract': protocol_extra,
                'incumbent': GUIDANCE['baseline'], 'limits': budget.report()['limits'],
                'implementation': {str(p): digest((root/p).read_text(encoding='utf-8-sig')) for p in (
                    Path('keel/outer_improvement.py'), Path('examples/evaluate_diagnosis.py'), Path('keel/core.py'),
                    Path('keel/execution.py'), Path('keel/models.py'), Path('keel/outer_validation_cases.py'), Path('keel/outer_feedback.py'), Path('examples/run_outer_improvement.py'), Path('keel/guard_recovery.py'))},
                'scope': 'Development harness qualification, not held-out repair evaluation.'}
    # Compare the persisted JSON representation (tuple case specs serialize as lists).
    manifest = json.loads(json.dumps(manifest))
    reused = None
    if reuse_proposal is not None:
        source = Path(reuse_proposal)
        old_manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
        old_report = json.loads((source/'report.json').read_text(encoding='utf-8'))
        reused = json.loads((source/'proposal.json').read_text(encoding='utf-8'))
        expected = {k: v for k, v in manifest.items() if k not in ('implementation', 'recover_guards')}
        if ({k: v for k, v in old_manifest.items() if k not in ('implementation', 'recover_guards')} != expected
                or digest(old_manifest) != old_report['manifest_sha256']
                or old_report['status'] != 'incomplete' or old_report.get('records') != []
                or old_report.get('pending_call') != 'proposal'
                or old_report['budget']['model_calls'] != 1
                or old_report['budget']['tool_calls'] != 0
                or reused.get('tokens') is None
                or reused['tokens'] != old_report['budget']['tokens']
                or any(source.glob('*/trial.json'))):
            raise ValueError('Cannot migrate incompatible or ambiguous proposal state')
        raw_candidates = json.loads(reused['content'])
        if recover_guards:
            from keel.guard_recovery import canonicalize_candidate_names
            restored, _ = canonicalize_candidate_names(raw_candidates)
        else:
            restored = validate_candidates(raw_candidates)
        if feedback is not None and len(restored) > 1:
            raise ValueError('Feedback replay permits at most one candidate')
        manifest['proposal_reuse'] = {'source_files': {
            name: digest(json.loads((source/name).read_text(encoding='utf-8')))
            for name in ('manifest.json', 'report.json', 'proposal.json')},
            'previous_implementation': old_manifest['implementation'],
            'previous_recover_guards': old_manifest.get('recover_guards', False),
            'scope': 'Explicit implementation migration; reuse raw proposal and carry usage, no retry.'}
        if not resume:
            for key in ('model_calls', 'tokens', 'tool_calls'):
                setattr(budget, key, old_report['budget'][key])
            budget.started -= old_report['budget']['wallclock_seconds']
    if resume:
        if json.loads((output/'manifest.json').read_text(encoding='utf-8')) != manifest:
            raise ValueError('Resume input or implementation mismatch')
        previous = json.loads((output/'report.json').read_text(encoding='utf-8'))
        if previous.get('pending_call'):
            raise ValueError('Interrupted proposal retained; automatic paid retry disabled')
        counters = previous['budget']
        for path in output.glob('*/trial.json'):
            completed = load_completed(path.parent)
            if completed['budget']['model_calls'] > counters['model_calls']:
                counters = completed['budget']
        for key in ('model_calls', 'tokens', 'tool_calls'):
            setattr(budget, key, counters[key])
        budget.started -= counters['wallclock_seconds']
    else:
        atomic_json(output/'manifest.json', manifest)
    report = {'status': 'running', 'records': [], 'manifest_sha256': digest(manifest)}
    def checkpoint():
        report['budget'] = budget.report()
        atomic_json(output/'report.json', report)
    checkpoint()
    try:
        messages = [{'role': 'system', 'content':
            'Propose at most three general diagnostic instruction alternatives. '
            'Only guidance strings can change. Do not include task answers, repository-specific fixes, '
            'new tools, changed scoring, permissions or budgets. Return the requested JSON.'},
            {'role': 'user', 'content': json.dumps({
                'incumbent': GUIDANCE['baseline'],
                'development_observations': [
                    'Repeating an observed symptom may not distinguish competing causes.',
                    'A conclusion without executed supporting evidence does not establish diagnosis.'],
                'goal': 'Improve grounded diagnosis on separately executed synthetic cases.'})}]
        if feedback is not None:
            messages[0]['content'] = messages[0]['content'].replace('at most three', 'at most one')
            messages[1]['content'] = json.dumps({
                'incumbent': GUIDANCE['baseline'],
                'development_trajectories': feedback['examples'],
                'goal': 'Propose one general guidance candidate addressing the observed failures. '
                        'Do not name the shown fixtures or encode their answers. Scoring remains unchanged.'})
        def prepare(raw_value):
            if not recover_guards:
                return validate_candidates(raw_value)
            from keel.guard_recovery import canonicalize_candidate_names
            normalized, incident = canonicalize_candidate_names(raw_value)
            record = {'incident': incident, 'budget': budget.report(), 'scope': 'Lossless host identity mapping; not a diagnosis or provider retry'}
            atomic_json(output/'candidate-identities.json', record)
            return validate_candidates({'candidates': normalized})
        if resume:
            candidates = validate_candidates({'candidates': json.loads((output/'candidates.json').read_text(encoding='utf-8'))})
            proposal = json.loads((output/'proposal.json').read_text(encoding='utf-8'))
            receipt = json.loads((output/'proposal-receipt.json').read_text(encoding='utf-8'))
            if receipt != {'proposal': digest(proposal), 'candidates': digest(candidates)}:
                raise ValueError('Proposal receipt mismatch')
            if recover_guards and validation is None:
                from keel.guard_recovery import canonicalize_candidate_names
                normalized, incident = canonicalize_candidate_names(json.loads(proposal['content']))
                saved_mapping = json.loads((output/'candidate-identities.json').read_text(encoding='utf-8'))
                if normalized != candidates or saved_mapping['incident'] != json.loads(json.dumps(incident)):
                    raise ValueError('Candidate identity mapping mismatch')
        elif reused is not None:
            candidates = prepare(json.loads(reused['content']))
            atomic_json(output/'proposal.json', reused)
            atomic_json(output/'candidates.json', candidates)
            atomic_json(output/'proposal-receipt.json', {'proposal': digest(reused), 'candidates': digest(candidates)})
            checkpoint()
        elif validation is not None:
            candidates = validate_candidates({'candidates': validation['candidates']})
            proposal = {'source': validation['source'], 'scope': 'Frozen pilot candidates; no new proposal call'}
            atomic_json(output/'proposal.json', proposal)
            atomic_json(output/'candidates.json', candidates)
            atomic_json(output/'proposal-receipt.json', {'proposal': digest(proposal), 'candidates': digest(candidates)})
        else:
            budget.allow_model(len(json.dumps(messages).encode()), 2048)
            report['pending_call'] = 'proposal'
            checkpoint()
            print('[Outer improvement] proposing <=1 prompt candidate' if feedback is not None else
                  '[Outer improvement] proposing <=3 prompt candidates', flush=True)
            try:
                schema = json.loads(json.dumps(SCHEMA))
                if feedback is not None:
                    schema['properties']['candidates']['maxItems'] = 1
                if recover_guards:
                    schema['properties']['candidates']['items']['properties']['id'] = {'type': 'string', 'minLength': 1}
                reply = model.complete_json(messages, schema=schema,
                                            timeout=min(60, budget.remaining), max_output=2048)
            except ModelError as error:
                if error.tokens is not None:
                    budget.charge_tokens(error.tokens)
                raise
            # Required raw checkpoint precedes validation and usage-dependent transitions.
            atomic_json(output/'proposal.json', {'content': reply.content, 'tokens': reply.tokens})
            budget.charge_tokens(reply.tokens if reply.tokens is not None else
                                 len(json.dumps(messages).encode()) + len(reply.content.encode()))
            candidates = prepare(json.loads(reply.content))
            if feedback is not None and len(candidates) > 1:
                raise ValueError('Feedback replay permits at most one candidate')
            report.pop('pending_call', None)
            atomic_json(output/'candidates.json', candidates)
            atomic_json(output/'proposal-receipt.json', {
                'proposal': digest(json.loads((output/'proposal.json').read_text(encoding='utf-8'))),
                'candidates': digest(candidates)})
            checkpoint()
        arms = [{'id': 'incumbent', 'guidance': GUIDANCE['baseline']}] + candidates
        for index, (case_id, family_id, cause) in enumerate(cases):
            # Alternate order; no arm receives another arm's transcript or hidden oracle.
            for arm in arms if index % 2 == 0 else list(reversed(arms)):
                print(f'[Outer improvement] {case_id} / {arm["id"]}', flush=True)
                arm_output = output/f'{case_id}-{arm["id"]}'
                if arm_output.exists():
                    result = load_completed(arm_output)
                else:
                    result = trial(model, families[family_id], cause, 'baseline',
                               arm_output, budget.started+max_seconds,
                               guidance=arm['guidance'], budget=budget, max_output=2048, protocol_extra=protocol_extra, recover_guards=recover_guards)
                report['records'].append({'case': case_id, 'arm': arm['id'],
                                          'passed': result['score']['passed'], 'metrics': result['score'],
                                          'protocol_failure': result.get('protocol_failure'),
                                          'guard_events': len(result.get('guard_events', []))})
                checkpoint()
        report['summary'] = {arm['id']: {
            'guard_events': sum(row.get('guard_events', 0) for row in report['records'] if row['arm'] == arm['id']),
            'cases': sum(row['arm'] == arm['id'] for row in report['records']),
            'grounded_passes': sum(row['passed'] for row in report['records'] if row['arm'] == arm['id']),
            'protocol_failures': sum(bool(row['protocol_failure']) for row in report['records'] if row['arm'] == arm['id']),
            'correct_conclusions': sum(row['metrics']['correct_conclusion'] for row in report['records'] if row['arm'] == arm['id']),
            'correct_predictions': sum(row['metrics']['correct_counterfactual_predictions'] for row in report['records'] if row['arm'] == arm['id'])
        } for arm in arms}
        report.update(status='completed', selection=select(report['records'], candidates, cases=cases))
    except Exception as error:
        report.update(status='incomplete', error_type=type(error).__name__)
        from keel.guard_recovery import GuardViolation
        if isinstance(error, GuardViolation):
            report['guard_failure'] = error.incident.record()
        raise
    finally:
        checkpoint()
    return report
