"""Experimental resolved-call graph ordering; never adds retrieval candidates."""
import math

POLICY = dict(name='resolved_call_ppr_rrf_v1', damping=.85, iterations=30,
              rrf_constant=60, baseline_weight=2, graph_weight=1, edge_limit=200000)


def rank_structure(rows, edges):
    """Personalize PageRank with original ranks, then combine ranks at fixed 2:1."""
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate candidate IDs')
    if not rows:
        return []
    if len(edges) > POLICY['edge_limit']:
        return [{**r, 'structural_evidence': {'status': 'edge_limit', 'policy': POLICY}} for r in rows]
    pairs = sorted({(a,b) for a,b in edges if a and b and a != b})
    if not pairs:
        return [{**r, 'structural_evidence': {'status': 'no_resolved_edges', 'policy': POLICY}} for r in rows]
    nodes = sorted({r['id'] for r in rows} | {n for edge in pairs for n in edge})
    prior = {r['id']: 1/(60+i) for i,r in enumerate(rows,1)}
    total = sum(prior.values())
    prior = {n: prior.get(n,0)/total for n in nodes}
    outgoing = {n: [] for n in nodes}
    for a,b in pairs:
        outgoing[a].append(b)
    current = dict(prior)
    damping = POLICY['damping']
    for _ in range(POLICY['iterations']):
        dangling = sum(current[n] for n in nodes if not outgoing[n])
        following = {n: (1-damping+damping*dangling)*prior[n] for n in nodes}
        for a in nodes:
            if outgoing[a]:
                value = damping*current[a]/len(outgoing[a])
                for b in outgoing[a]:
                    following[b] += value
        current = following
    order = sorted(rows, key=lambda r: (-current[r['id']], r['id']))
    graph_ranks = {r['id']: i for i,r in enumerate(order,1)}
    ranked = []
    for position,row in enumerate(rows,1):
        score = 2/(60+position)+1/(60+graph_ranks[row['id']])
        if not math.isfinite(score):
            raise ValueError('Nonfinite graph score')
        ranked.append({**row, 'score': score, 'structural_evidence': dict(status='ranked',
            baseline_rank=position, graph_rank=graph_ranks[row['id']],
            graph_score=current[row['id']], nodes=len(nodes), edges=len(pairs), policy=POLICY)})
    return sorted(ranked, key=lambda r: (-r['score'],r['structural_evidence']['baseline_rank'],r['id']))


def rank_index_structure(index, rows):
    edges = index.db.execute('SELECT source_id,target_id FROM calls WHERE source_id IS NOT NULL '
        'AND target_id IS NOT NULL ORDER BY source_id,target_id LIMIT ?', (POLICY['edge_limit']+1,)).fetchall()
    return rank_structure(rows, [(r[0],r[1]) for r in edges])
