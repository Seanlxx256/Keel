"""Evidence inventory for recovery rounds, not a semantic correctness oracle."""
from .core import digest
from .repair_checkpoints import verification_score


class RecoveryProgress:
    def __init__(self, workspace):
        self.ws = workspace
        self.pending = None
        self.rounds = []

    def begin(self, decision, verification, decision_fact_id):
        if decision['action'] == 'stop':
            return
        self.pending = {'round': len(self.rounds) + 1, 'decision_fact_id': decision_fact_id,
                        'question': decision['next_check'], 'hypothesis': decision['hypothesis'],
                        'route': decision['action'], 'baseline': verification}
        self.ws.trace.emit('critic', 'recovery_question_started', round=self.pending['round'],
                           decision_fact_id=decision_fact_id)

    def review(self, verification, *, terminal_status=None):
        if self.pending is None:
            return self.rounds[-1] if self.rounds else None
        pending = self.pending
        facts = [row for row in self.ws.ledger.summaries()
                 if row['fact_id'] > pending['decision_fact_id']]
        observations = [row for row in facts if row['kind'] in {'file', 'symbol'}
                        and row['role'] != 'critic']
        # Only a new verifier receipt matching these results establishes revalidation.
        matches = {digest(self.ws.ledger.recall(row['fact_id'])): row['fact_id'] for row in facts
                   if row['kind'] == 'test' and row['role'] == 'verifier'}
        verified = bool(verification) and all(digest(row) in matches for row in verification)
        comparison = {'status': 'not_reverified', 'scope': 'No matching new verifier facts in this round.'}
        if verified:
            comparison = {'status': 'incomparable',
                          'scope': 'Fresh verification exists, but comparable grouped test counts may be unavailable.'}
            before, after = verification_score(pending['baseline']), verification_score(verification)
            if before and after and before[0] == after[0]:
                comparison = {'status': 'improved' if after[1] < before[1] else
                              'regressed' if after[1] > before[1] else 'tied',
                              'before_rank': list(before[1]), 'after_rank': list(after[1]),
                              'test_universe_sha256': after[0][0],
                              'scope': 'PASS_TO_PASS failures, then FAIL_TO_PASS failures; not semantic proof.'}
        row = {key: value for key, value in pending.items() if key != 'baseline'}
        row.update(observation_fact_ids=[item['fact_id'] for item in observations],
                   verification_fact_ids=[matches[digest(item)] for item in verification] if verified else [],
                   observation_preview=[{**item, 'summary': item['summary'][:100]} for item in observations[-4:]],
                   omitted_observation_previews=max(0, len(observations)-4),
                   verification_comparison=comparison, terminal_status=terminal_status,
                   check_execution='not_established', hypothesis_status='unverified',
                   scope='Facts were recorded after the decision; relevance, freshness and performance of next_check '
                         'are not established by their presence. No automatic stop or reward.')
        self.rounds.append(row)
        self.pending = None
        fact = self.ws.ledger.add('decision', 'critic', 'Host recovery progress inventory', row)
        row['inventory_fact_id'] = fact
        self.ws.trace.emit('critic', 'recovery_question_reviewed', round=row['round'], fact_id=fact,
                           verification_status=comparison['status'])
        return row

    def context(self, row):
        if row is None:
            return None
        # Bodies remain in existing source handoff; don't pretend an ID is a source read.
        return {key: value for key, value in row.items()
                if key not in {'observation_fact_ids', 'verification_fact_ids'}}

    def report(self):
        return {'rounds': self.rounds, 'scope': 'Experimental evidence inventory, not verified hypothesis learning.'}
