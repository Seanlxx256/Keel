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
    def __init__(self, model, check, transcript=None, *, transport_retries=0):
        self.model, self.check, self.transcript = model, check, transcript
        self.transport_retries, self.budget = transport_retries, None

    def bind_budget(self, budget):
        self.budget = budget

    def record(self, event, **payload):
        if self.transcript is not None:
            import json
            import os
            import time
            with self.transcript.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps({'event': event, 'time': time.time(), **payload}, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())

    def __getattr__(self, name):
        value = getattr(self.model, name)
        if name not in {'complete', 'complete_json'} or not callable(value):
            return value
        def dispatch(*args, **kwargs):
            from .core import ModelError
            self.check()
            self.record('request', method=name, args=args, kwargs=kwargs,
                        dispatch_model_call=self.budget.model_calls if self.budget else None)
            try:
                reply = value(*args, **kwargs)
            except Exception as error:
                from .core import ModelCompletionError
                details={}
                reason=getattr(error,'transport_reason',None)
                if reason in {'TimeoutError','ConnectionResetError','ConnectionAbortedError','BrokenPipeError','RemoteDisconnected','IncompleteRead','SSLEOFError','gaierror','SSLCertVerificationError','OSError','str'}:
                    details['transport_reason']=reason
                if isinstance(error,ModelCompletionError):
                    source=error.diagnostics if isinstance(error.diagnostics,dict) else {}
                    safe={}
                    for key in ('refusal_present','tool_calls_present','assistant_role','content_present'):
                        if type(source.get(key)) is bool:
                            safe[key]=source[key]
                    for key in ('prompt_tokens','completion_tokens','max_output'):
                        if type(source.get(key)) is int and source[key]>=0:
                            safe[key]=source[key]
                    if source.get('finish_reason') in ('stop','length','content_filter','tool_calls','function_call'):
                        safe['finish_reason']=source['finish_reason']
                    details['completion_diagnostics']=safe
                    if type(error.tokens) is int and error.tokens>=0:
                        details['tokens']=error.tokens
                self.record('error', error_type=type(error).__name__,**details)
                raise
            if self.transcript is not None:
                self.record('response', content=reply.content, tokens=reply.tokens, metadata=getattr(reply, 'metadata', None))
            try:
                self.check()
            except ModelError as error:
                raise ModelError(str(error), tokens=reply.tokens) from None
            return reply
        def invoke(*args, **kwargs):
            from .model_transport import invoke_with_retries
            return invoke_with_retries(dispatch, args, kwargs, budget=self.budget,
                                      retries=self.transport_retries, record=self.record)
        return invoke
