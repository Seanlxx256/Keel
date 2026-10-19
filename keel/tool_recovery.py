"""Bounded external symbol queries using the shared recovery controller."""
import re
import time

from .experience import RecoverySession, environment


def symbol_queries(invoke, terms, *, version, store=None, max_calls=8, timeout=210):
    if type(max_calls) is not int or not 1 <= max_calls <= 8:
        raise ValueError('Symbol query call limit must be between 1 and 8')
    calls, observations, results, events = 0, [], [], []
    terms, queried = list(terms), []
    deadline = time.monotonic()+timeout
    for term in terms:
        if calls >= max_calls:
            break
        queried.append(term)
        mode = {'substring': True, 'pattern': term, 'root': False}
        session = RecoverySession(task='symbol-query:'+term, store=store,
            max_actions=min(2, max_calls-calls-1), deadline=deadline)
        def operation():
            nonlocal calls
            if calls >= max_calls:
                raise ValueError('Symbol query call budget exhausted')
            calls += 1
            try:
                value = invoke(mode['pattern'], mode['substring'], min(30, session.remaining()))
            except Exception as error:
                observations.append({'term': term, 'pattern': mode['pattern'], 'substring': mode['substring'],
                    'error_type': type(error).__name__, 'error': str(error)[:500]})
                raise
            observations.append({'term': term, 'pattern': mode['pattern'], 'substring': mode['substring'], 'response': value})
            return value
        def is_overflow(error):
            return isinstance(error, ValueError) and bool(re.match(r'^Matched \d+>max_matches=\d+ symbols\.', str(error)))
        try:
            payload = session.run(operation, stage='external_symbol_query',
                facts=environment(tool='serena.find_symbol', tool_version=version, max_matches=100,
                                  query_policy='bounded-relative-and-root-v1'),
                classify=lambda error: 'match_overflow' if is_overflow(error) else type(error).__name__,
                actions={'exact_symbol_query_v1': {
                    'categories': ['match_overflow'],
                    'probe': lambda error: {'applicable': mode['substring'] and is_overflow(error) and calls < max_calls,
                        'check': 'upstream_match_limit_error_and_remaining_call_budget'},
                    'apply': lambda remaining: mode.update(substring=False)},
                    'root_symbol_query_v1': {
                    'categories': ['match_overflow'],
                    'probe': lambda error: {'applicable': not mode['substring'] and not mode['root'] and
                        not term.startswith('/') and is_overflow(error) and calls < max_calls,
                        'check': 'relative_exact_still_overflowed_and_remaining_call_budget'},
                    'apply': lambda remaining: mode.update(pattern='/'+term, root=True)}},
                verify=lambda payload: isinstance(payload, list) and all(isinstance(row, dict) for row in payload))
            results.extend(payload)
        finally:
            events.extend(session.events)
    return {'symbols': results, 'observations': observations, 'recovery': events,
            'tool_calls': calls, 'max_tool_calls': max_calls,
            'unqueried_terms': terms[len(queried):],
            'verification_scope': 'Query response shape only; source range validation is performed by the adapter'}
