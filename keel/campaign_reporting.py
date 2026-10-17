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
    def __init__(self, model, check):
        self.model, self.check = model, check

    def __getattr__(self, name):
        value = getattr(self.model, name)
        if name not in {'complete', 'complete_json'} or not callable(value):
            return value
        def invoke(*args, **kwargs):
            from .core import ModelError
            self.check()
            reply = value(*args, **kwargs)
            try:
                self.check()
            except ModelError as error:
                raise ModelError(str(error), tokens=reply.tokens) from None
            return reply
        return invoke
