"""Trusted-host composition guard, not a proof of backend implementation honesty."""


def require_shared_domain(store, **components):
    from .governance import GovernanceUnavailable
    expected=getattr(store,'transaction_domain',None)
    if expected is None:raise GovernanceUnavailable('Control storage transaction domain unavailable')
    for name,component in components.items():
        try:actual=getattr(component,'transaction_domain',None)
        except Exception:
            raise GovernanceUnavailable('Storage transaction domain unavailable: '+name) from None
        # Identity, not path/string equality: separate managers cannot join an
        # already-open transaction simply because they name the same database.
        if actual is not expected:
            raise GovernanceUnavailable('Storage transaction domain mismatch: '+name)
