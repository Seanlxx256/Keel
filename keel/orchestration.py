"""Two orchestrators over shared phases and host-validated recovery routes."""
from .core import BudgetExceeded, ModelError, PolicyDenied

PHASES = ("scout", "planner", "implementer", "verifier", "auditor")
EXPECTED_ERRORS = (BudgetExceeded, PolicyDenied, ModelError, ValueError, OSError, SyntaxError)


def next_phase(phase, result, *, approval=False):
    requested = result.pop('_next_role', None)
    if result['failure']:
        return None if phase == 'critic' else 'critic'
    allowed = {'scout': {'planner'}, 'planner': {'implementer'}, 'implementer': {'verifier'},
               'verifier': {'auditor', 'critic'}, 'auditor': set(), 'critic': {'scout', 'implementer'}}
    if requested is not None:
        if requested not in allowed[phase]:
            raise PolicyDenied('Invalid recovery role transition')
        following = requested
    else:
        following = PHASES[PHASES.index(phase)+1] if phase in PHASES[:-1] else None
    if approval and phase == 'planner' and following == 'implementer':
        return 'approval'
    return following


def execute(engine, stages, result, on_error, output, budget, **approval_options):
    if engine == "langgraph":
        from .adapters.langgraph import execute_graph
        return execute_graph(stages, result, on_error, output, budget, **approval_options)
    completed = []
    phase, transitions = 'scout', 0
    while phase is not None:
        try:
            budget.check()
            transitions += 1
            if transitions > max(16, budget.limits.max_model_calls * 6 + 16):
                raise BudgetExceeded('Orchestration transition budget exhausted')
            stages[phase]()
        except EXPECTED_ERRORS as error:
            on_error(error)
        completed.append(phase)
        phase = next_phase(phase, result)
    return {"completed_nodes": completed}
