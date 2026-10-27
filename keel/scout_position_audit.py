"""Descriptive paired position audit of completed score reports; no policy tuning."""
import math


def _index(report):
    if report.get('status') != 'completed':
        raise ValueError('Require completed score report')
    rows = {}
    for row in report['rows']:
        key = row['sample']
        if key in rows:
            raise ValueError('Duplicate sample')
        candidates = row['candidate_scores']
        ordered = sorted(candidates, key=lambda c: c['token_position'])
        positions = [c['token_position'] for c in ordered]
        if not ordered or len(set(positions)) != len(positions):
            raise ValueError('Require unique candidate positions')
        values = {}
        for rank, candidate in enumerate(ordered):
            location = candidate['location']
            p = candidate['probability']
            label = candidate['teacher_member']
            if location in values or not math.isfinite(p) or not 0 <= p <= 1 or label not in (0, 1):
                raise ValueError('Invalid candidate record')
            values[location] = (p, label, rank / max(1, len(ordered)-1))
        rows[key] = values
    if not rows:
        raise ValueError('Empty report')
    return rows


def audit_pair(before, after):
    """Keep query/location identity fixed, expose score drift without causal claims."""
    for field in ('training_receipt_sha256', 'dataset_sha256', 'checkpoint_step', 'selection_policy'):
        if field not in before or before[field] != after.get(field):
            raise ValueError('Paired report identity differs: ' + field)
    if before.get('score_representation','legacy')!=after.get('score_representation','legacy'):
        raise ValueError('Paired score representation differs')
    left, right = _index(before), _index(after)
    if left.keys() != right.keys():
        raise ValueError('Paired sample coverage differs')
    threshold = before['selection_policy']['threshold']
    changes = []
    for sample, candidates in left.items():
        if candidates.keys() != right[sample].keys():
            raise ValueError('Paired candidate coverage differs')
        for location, (p, label, position) in candidates.items():
            q, other_label, other_position = right[sample][location]
            if label != other_label:
                raise ValueError('Teacher membership changed')
            changes.append(dict(sample=sample, location=location, teacher_member=label,
                probability_before=p, probability_after=q, probability_delta=q-p,
                position_before=position, position_after=other_position,
                position_delta=other_position-position,
                threshold_crossed=(p >= threshold) != (q >= threshold)))
    moving = [c for c in changes if c['position_delta'] != 0]
    x = [c['position_delta'] for c in moving]
    y = [c['probability_delta'] for c in moving]
    correlation = None
    if len(x) > 1:
        mx, my = sum(x)/len(x), sum(y)/len(y)
        xx = sum((v-mx)**2 for v in x); yy = sum((v-my)**2 for v in y)
        if xx and yy:
            correlation = sum((a-mx)*(b-my) for a,b in zip(x,y)) / math.sqrt(xx*yy)
    return dict(samples=len(left), candidates=len(changes), moved_candidates=len(moving),
        mean_absolute_probability_change=sum(abs(c['probability_delta']) for c in changes)/len(changes),
        threshold_crossings=sum(c['threshold_crossed'] for c in changes),
        position_score_delta_correlation=correlation, candidates_detail=changes,
        scope='Descriptive exposed-query audit; threshold crossing is not capped set selection; '
              'correlation is not causality or independent generalization')
