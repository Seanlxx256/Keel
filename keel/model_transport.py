"""Explicit provider retries using the caller's existing global budget."""
import json
import time

from .core import BudgetExceeded, ModelTransportError


def invoke_with_retries(invoke, args, kwargs, *, budget, retries, record):
    if type(retries) is not int or not 0 <= retries <= 2:
        raise ValueError('Transport retries must be an integer from 0 to 2')
    if retries and budget is None:
        raise ValueError('Transport retry requires a bound shared budget')
    # Byte estimate intentionally conservative; provider usage may be unavailable
    # even when the remote service executed a disconnected request.
    estimate = len(json.dumps({'args': args, 'schema': kwargs.get('schema')}, ensure_ascii=False).encode())
    maximum = kwargs.get('max_output', 0)
    for attempt in range(retries + 1):
        request = dict(kwargs)
        if budget is not None:
            budget.check()
            request['timeout'] = min(kwargs['timeout'], budget.remaining)
        try:
            return invoke(*args, **request)
        except ModelTransportError as error:
            if not retries:
                raise
            unknown = error.tokens is None
            charged = estimate + maximum if unknown else error.tokens
            record('transport_failure', attempt=attempt, usage_unknown=unknown,
                   charged_tokens=charged, retry_requested=attempt < retries)
            if unknown:
                reservations = getattr(budget, 'transport_unknown_reservations', [])
                reservations.append({'dispatch_model_call': budget.model_calls, 'reserved_tokens': charged,
                                     'scope': 'Usage unknown; conservative budget reservation, not observed usage'})
                budget.transport_unknown_reservations = reservations
            budget.charge_tokens(charged)
            if attempt == retries:
                # This failure was already charged here, not again by the role.
                raise ModelTransportError(str(error)) from None
            if budget.remaining <= 2:
                raise BudgetExceeded('Insufficient time for model transport retry')
            record('transport_retry_wait', attempt=attempt + 1, seconds=2)
            time.sleep(2)
            budget.allow_model(estimate, maximum)
