"""Evidence inventory for recovery rounds, not a semantic correctness oracle."""
import hashlib
import json
import re

from .core import digest
from .repair_checkpoints import verification_score


class RecoveryProgress:
    def __init__(self, workspace):
        self.ws = workspace
        self.pending = None
        self.rounds = []
        self.targeted_seen = set()

    def targeted_source(self, question, files, max_bytes=4500):
        """Resolve explicitly named definitions only within known readable files."""
        from .localization import symbol_structure
        from .proposals import located_source_evidence
        tokens = set(re.findall(r'[A-Za-z_][A-Za-z_0-9]*', question))
        windows, omitted, remaining = [], [], max_bytes
        for name in list(dict.fromkeys(files))[:4]:
            if not name.endswith('.py'):
                continue
            try:
                text = self.ws.read(name, role='critic')['value']
            except (OSError, ValueError):
                continue
            structure = symbol_structure(name, text)
            matches = [(line, symbol) for line, symbol in structure['symbols'] if symbol in tokens]
            for line, symbol in matches[:3]:
                payload = located_source_evidence(name, text, [line])
                for window in payload['windows']:
                    if not window['start_line'] <= line <= window['end_line']:
                        continue
                    key = (name, line, payload['sha256'])
                    if key in self.targeted_seen:
                        continue
                    self.targeted_seen.add(key)
                    entry = {'path': name, 'symbol': symbol, **window, 'source_sha256': payload['sha256']}
                    size = len(json.dumps(entry).encode())
                    if size > remaining:
                        omitted.append({'path': name, 'symbol': symbol, 'reason': 'complete_definition_exceeds_budget'})
                        continue
                    fact = self.ws.ledger.add('file', 'critic', 'Targeted definition evidence', entry)
                    windows.append({'fact_id': fact, **entry})
                    remaining -= size
        return {'windows': windows, 'omitted': omitted,
                'scope': 'Read-only definitions explicitly named in the diagnostic question; '
                         'no reproducer executed, no causal claim or new edit permission.'}

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
        context = {key: value for key, value in row.items()
                   if key not in {'observation_fact_ids', 'verification_fact_ids'}}
        context['source_handoff'] = self.source_handoff(row)
        return context

    def source_handoff(self, row, max_bytes=4500):
        """Carry whole, relevant previously observed windows, with fresh checks.

        Lexical ranking is advisory, not proof that a diagnostic check was done.
        No new source ranges or write permissions are granted here.
        """
        history = [previous for previous in self.rounds
                   if previous.get('round', 0) <= row.get('round', len(self.rounds))]
        ids = list(dict.fromkeys(fact for previous in [*history, row]
                                for fact in previous.get('observation_fact_ids', [])))
        terms = set(re.findall(r'[A-Za-z_][A-Za-z_0-9]{3,}', row['question']))
        candidates = []
        for fact in ids:
            payload = self.ws.ledger.recall(fact)
            if not isinstance(payload, dict) or not isinstance(payload.get('path'), str):
                continue
            windows = payload.get('windows', [payload])
            for window in windows:
                if not isinstance(window, dict) or not isinstance(window.get('text'), str):
                    continue
                start, end = window.get('start_line'), window.get('end_line')
                if type(start) is not int or type(end) is not int or not 1 <= start <= end:
                    continue
                text = window['text']
                score = sum(term in text or term in payload['path'] for term in terms)
                if score:
                    candidates.append((score, fact, payload, window))
        included, omitted, seen, current = [], [], set(), {}
        # Bound actual reads as well as prompt bytes. Prefer strongest matches.
        ranked = sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)
        remaining = max_bytes
        for _, fact, payload, window in ranked[:12]:
            name = payload['path']
            key = (name, window['start_line'], window['end_line'], window['text'])
            if key in seen:
                continue
            seen.add(key)
            entry = {'fact_id': fact, 'path': name, 'start_line': window['start_line'],
                     'end_line': window['end_line'], 'text': window['text']}
            size = len(json.dumps(entry, ensure_ascii=False).encode())
            if size > remaining:
                omitted.append({'fact_id': fact, 'reason': 'whole_window_exceeds_handoff_budget'})
                continue
            if name not in current:
                try:
                    current[name] = self.ws.read(name, role='critic')['value']
                except (OSError, ValueError):
                    current[name] = None
            source = current[name]
            source_hash = hashlib.sha256(source.encode()).hexdigest() if source is not None else None
            expected = payload.get('source_sha256', payload.get('sha256'))
            if (source is None or (expected is not None and source_hash != expected) or
                    ''.join(source.splitlines(True)[window['start_line']-1:window['end_line']]) != window['text']):
                omitted.append({'fact_id': fact, 'reason': 'source_changed_or_unavailable'})
                continue
            entry.update(current_source_sha256=source_hash,
                         freshness='whole_file_hash_and_window' if expected else 'window_matches_current_source')
            size = len(json.dumps(entry, ensure_ascii=False).encode())
            if size > remaining:
                omitted.append({'fact_id': fact, 'reason': 'whole_window_exceeds_handoff_budget'})
                continue
            included.append(entry)
            remaining -= size
        return {'windows': included, 'omitted': omitted, 'unexamined_candidates': max(0, len(ranked)-12),
                'scope': 'Untrusted source, lexically selected from prior observations and checked now; '
                         'not evidence of executed probes, understood contracts or write authorization.'}

    def report(self):
        return {'rounds': self.rounds, 'scope': 'Experimental evidence inventory, not verified hypothesis learning.'}
