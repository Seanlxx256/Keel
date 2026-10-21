"""Describe observed trajectories without claiming a causal recovery benefit."""


def trajectory(result, passed):
    if not passed:
        return 'failed'
    rounds = result.get('verification_attempts', [])
    if not rounds:
        return 'unclassified_pass'
    if len(rounds) == 1:
        return 'pre_verification_recovery_pass' if result.get('recovery', {}).get('used_actions', 0) else 'first_verification_pass'
    prior_failed = any(any(entry.get('returncode') != 0 for entry in row.get('verification', [])) for row in rounds[:-1])
    if not prior_failed:
        return 'unclassified_pass'
    replanned = (any(row.get('action') == 'replan' for row in result.get('recovery_decisions', [])) and
                 any(row.get('revision', 0) > 0 for row in result.get('plans', [])))
    return 'replanning_recovery_pass' if replanned else 'verification_recovery_pass'


class FrozenModel:
    """Reject code drift before a provider call and account for in-flight usage."""
    def __init__(self, model, check, transcript=None):
        self.model, self.check, self.transcript = model, check, transcript

    def record(self, event, **payload):
        if self.transcript is not None:
            import json
            import os
            with self.transcript.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps({'event': event, **payload}, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())

    def __getattr__(self, name):
        value = getattr(self.model, name)
        if name not in {'complete', 'complete_json'} or not callable(value):
            return value
        def invoke(*args, **kwargs):
            from .core import ModelError
            self.check()
            self.record('request', method=name, args=args, kwargs=kwargs)
            try:
                reply = value(*args, **kwargs)
            except Exception as error:
                self.record('error', error_type=type(error).__name__)
                raise
            if self.transcript is not None:
                self.record('response', content=reply.content, tokens=reply.tokens)
            try:
                self.check()
            except ModelError as error:
                raise ModelError(str(error), tokens=reply.tokens) from None
            return reply
        return invoke
