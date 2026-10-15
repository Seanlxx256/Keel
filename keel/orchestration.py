"""Two sequential orchestrators over the same Keel phase implementations."""
from .core import BudgetExceeded, ModelError, PolicyDenied

PHASES = ("scout", "planner", "implementer", "verifier", "auditor")
EXPECTED_ERRORS = (BudgetExceeded, PolicyDenied, ModelError, ValueError, OSError, SyntaxError)


def execute(engine, stages, result, on_error, output, budget):
    if engine == "langgraph":
        from .adapters.langgraph import execute_graph
        return execute_graph(stages, result, on_error, output, budget)
    completed = []
    for phase in PHASES:
        try:
            stages[phase]()
        except EXPECTED_ERRORS as error:
            on_error(error)
        completed.append(phase)
        if result["failure"]:
            stages["critic"]()
            completed.append("critic")
            break
    return {"completed_nodes": completed}
