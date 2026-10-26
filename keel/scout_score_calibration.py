"""One global threshold fitted only on explicit calibration rows."""
import bisect
import math
from .scout_candidate_scoring import select_candidates


def _prepared(rows,max_items):
    if not rows:raise ValueError('Require calibration rows')
    result=[]
    for row in rows:
        candidates=row['candidate_scores']
        probabilities=[c['probability'] for c in candidates]
        select_candidates(candidates,probabilities,max_items=max_items)
        if not candidates or len({c['location'] for c in candidates})!=len(candidates):raise ValueError('Require unique candidate locations')
        if any(type(c['teacher_member']) is not int or c['teacher_member'] not in (0,1) for c in candidates):
            raise ValueError('Invalid teacher membership')
        ranked=sorted(candidates,key=lambda c:(-c['probability'],c['location']))
        positives=sum(c['teacher_member'] for c in ranked)
        if not positives:raise ValueError('Require teacher members')
        prefix=[0]
        for c in ranked:prefix.append(prefix[-1]+c['teacher_member'])
        result.append((sorted(probabilities),prefix,positives))
    return result


def _metrics(prepared,threshold,max_items):
    exact=0;f1=0.;tp=fp=fn=0
    for probabilities,prefix,positives in prepared:
        count=min(max_items,len(probabilities)-bisect.bisect_left(probabilities,threshold))
        hits=prefix[count]
        exact+=count==positives==hits
        f1+=2*hits/(count+positives)
        tp+=hits;fp+=count-hits;fn+=positives-hits
    return {'samples':len(prepared),'exact_sets':exact,'macro_f1':f1/len(prepared),
            'true_positive_memberships':tp,'false_positive_memberships':fp,'false_negative_memberships':fn}


def threshold_metrics(rows,threshold,max_items=8):
    select_candidates([],[],threshold=threshold,max_items=max_items)
    return _metrics(_prepared(rows,max_items),threshold,max_items)


def fit_threshold(rows,max_items=8):
    prepared=_prepared(rows,max_items)
    grid={0.,0.5,1.}
    for probabilities,_,_ in prepared:
        for value in probabilities:
            grid.add(value)
            if value<1:grid.add(math.nextafter(value,1.))
    best=None;key=None
    for threshold in sorted(grid):
        metrics=_metrics(prepared,threshold,max_items)
        rank=(metrics['exact_sets'],metrics['macro_f1'],-abs(threshold-0.5),threshold)
        if key is None or rank>key:best={'threshold':threshold,**metrics};key=rank
    return {**best,'max_items':max_items,'grid_size':len(grid),
            'criterion':'Exact sets, then macro F1, then closest to0.5, then higher threshold',
            'scope':'Calibration fit only; no independent quality or oracle-count inference'}


def grouped_crosscheck(rows,max_items=8):
    groups=sorted({r['group'] for r in rows})
    if len(groups)<2:raise ValueError('Require at least two calibration groups')
    folds=[]
    for group in groups:
        training=[r for r in rows if r['group']!=group]
        held=[r for r in rows if r['group']==group]
        fitted=fit_threshold(training,max_items)
        folds.append({'group':group,'threshold':fitted['threshold'],
                      'metrics':threshold_metrics(held,fitted['threshold'],max_items),
                      'baseline':threshold_metrics(held,0.5,max_items)})
    return {'folds':folds,'scope':'Leave-one-query-group-out selection-rule check; model was trained on all groups, not unseen-task validation'}
