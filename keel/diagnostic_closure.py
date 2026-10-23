"""Host-owned completion predicates for diagnostic reviews, never repair acceptance."""


def execution_ids(observations):
    return {row['evidence_id'] for row in observations
            if row.get('kind') == 'execution' and not row.get('historical')}


def blocker_ids(observations):
    # Only outer executor failures establish an execution obstacle here. Child
    # errors can be caused by model code and require further diagnosis.
    return {row['evidence_id'] for row in observations
            if row.get('kind') == 'execution' and not row.get('historical')
            and (row.get('execution', {}).get('timeout') is True
                 or (type(row.get('execution', {}).get('returncode')) is int
                     and row['execution']['returncode'] != 0))}


def terminal_decision(proposal, observations, *, required):
    """Return host state and unmet predicate; relevance remains unverified."""
    cited = set(proposal['evidence_ids'])
    if proposal['action'] == 'blocked':
        matched = cited & blocker_ids(observations)
        if matched:
            return {'state': 'blocked_verified', 'evidence_ids': sorted(matched),
                    'reason': 'Current executor failure observed; root cause is not certified.'}
        return {'state': 'acquire', 'reason':
                'No current executor failure supports this blocker. Missing evidence is a '
                'collection task, not an execution obstacle. Design and execute a check; '
                'child script errors and historical results do not certify blocking.'}
    if required and not cited.intersection(execution_ids(observations)):
        return {'state': 'acquire', 'reason':
                'No fresh execution is cited. Execute a check for this investigation '
                'and cite its result; a proposed check or historical output is insufficient.'}
    return {'state': 'diagnosis_ready', 'reason':
            'Evidence linkage satisfied; diagnosis correctness and repair acceptance unverified.'}
