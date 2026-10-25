"""Turn verified completed validation failures into bounded proposal feedback."""
import hashlib
import json
from pathlib import Path
from examples.evaluate_diagnosis import digest, load_completed
from keel.outer_improvement import select, validate_candidates
from keel.outer_validation_cases import CASES_V2


def collect_feedback(source, config_hash):
    source = Path(source)
    report = json.loads((source/'report.json').read_text(encoding='utf-8'))
    manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    candidates = validate_candidates({'candidates': json.loads((source/'candidates.json').read_text(encoding='utf-8'))})
    proposal = json.loads((source/'proposal.json').read_text(encoding='utf-8'))
    receipt = json.loads((source/'proposal-receipt.json').read_text(encoding='utf-8'))
    expected = [(f'repeat-{repeat}-{name}', family, cause)
                for repeat in (1, 2) for name, family, cause in CASES_V2]
    cases = {name: (family, cause) for name, family, cause in expected}
    if (report['status'] != 'completed' or digest(manifest) != report['manifest_sha256']
            or manifest['config_sha256'] != config_hash
            or receipt != {'proposal': digest(proposal), 'candidates': digest(candidates)}
            or select(report['records'], candidates, cases=expected) != report['selection']):
        raise ValueError('Feedback input is not a matching completed validation')
    loaded = []
    arms = {'incumbent'} | {c['id'] for c in candidates}
    for row in report['records']:
        if row['case'] not in cases or row['arm'] not in arms:
            raise ValueError('Unknown feedback case or arm')
        trial = load_completed(source/(row['case']+'-'+row['arm']))
        if trial['score'] != row['metrics'] or trial['score']['passed'] != row['passed']:
            raise ValueError('Feedback score mismatch')
        loaded.append((row, trial))
    # Two distinct failure families, then one passed incumbent control from another family.
    chosen = []; families = set()
    for failed in (True, False):
        for row, trial in loaded:
            family, cause = cases[row['case']]
            if family in families or bool(row['passed']) == failed:
                continue
            if not failed and row['arm'] != 'incumbent':
                continue
            if failed and len(chosen) >= 2:
                break
            families.add(family)
            chosen.append((row, trial, family, cause))
            if not failed or len(chosen) >= 3:
                break
    if len(chosen) != 3:
        raise ValueError('Need two failed families and one passed control')
    from keel.outer_validation_cases import FAMILIES_V2
    feedback = []
    for row, trial, family, _ in chosen:
        feedback.append({'public_case': {k: FAMILIES_V2[family][k] for k in ('symptom', 'hypotheses', 'probes')},
                         'model_steps': trial['steps'],
                         'observations': [{k: o[k] for k in ('id', 'probe_id', 'result')}
                                          for o in trial.get('observations', [])],
                         'measured_outcome': row['metrics'],
                         'scope': 'Exposed development trajectory; no oracle truth table or fixture source supplied.'})
    return {'source': {name: hashlib.sha256((source/name).read_bytes()).hexdigest()
                       for name in ('report.json', 'manifest.json', 'candidates.json', 'proposal.json')},
            'cases': [(f'feedback-{index+1}', family, cause)
                      for index, (_, _, family, cause) in enumerate(chosen)],
            'examples': feedback,
            'scope': 'Failure-guided development replay, not independent selection.'}
