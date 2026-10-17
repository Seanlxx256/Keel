"""StateGraph with conditional recovery and in-process approval; no crash recovery."""
import sqlite3
from contextlib import closing
from typing import TypedDict

from ...orchestration import EXPECTED_ERRORS, PHASES, next_phase
from ...core import PolicyDenied


class GraphState(TypedDict):
    run_id: str
    completed: list[str]
    failed: bool
    ledger_path: str
    budget: dict


def require_dependencies():
    try:
        from langgraph.graph import StateGraph
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        raise ValueError('LangGraph adapter requires pip install -e ".[langgraph]"') from None


def execute_graph(stages, result, on_error, output, budget, *,
                  approval=None, approval_request=None, approval_guard=None):
    from langgraph.types import Command, interrupt
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.sqlite import SqliteSaver
    builder = StateGraph(GraphState)
    def node(phase):
        def invoke(state):
            try:
                stages[phase]()
            except EXPECTED_ERRORS as error:
                on_error(error)
            return {"completed": state["completed"] + [phase], "failed": bool(result["failure"]),
                    "budget": budget.report()}
        return invoke
    for phase in (*PHASES, "critic"):
        builder.add_node(phase, node(phase))
    if approval is not None:
        def approval_node(state):
            # No side effects before interrupt: this node restarts on resume.
            approved = interrupt({"run_id": state["run_id"], "kind": "before_declared_writes"})
            if not result["failure"]:
                try:
                    if approved is not True:
                        raise PolicyDenied("Operator denied planned writes")
                    approval_guard()
                except EXPECTED_ERRORS as error:
                    on_error(error)
            return {"completed": state["completed"] + ["approval"],
                    "failed": bool(result["failure"]), "budget": budget.report()}
        builder.add_node("approval", approval_node)
        builder.add_conditional_edges("approval", lambda state: "failed" if state["failed"] else "next",
                                      {"failed": "critic", "next": "implementer"})
    builder.add_edge(START, "scout")
    for phase in (*PHASES, 'critic'):
        def route(state, phase=phase):
            try:
                return next_phase(phase, result, approval=approval is not None) or END
            except EXPECTED_ERRORS as error:
                on_error(error)
                return END if phase == 'critic' else 'critic'
        targets = {name: name for name in (*PHASES, 'critic', END)}
        if approval is not None:
            targets['approval'] = 'approval'
        builder.add_conditional_edges(phase, route, targets)
    checkpoint_path = output / "checkpoints.sqlite"
    with closing(sqlite3.connect(checkpoint_path, check_same_thread=False)) as connection:
        saver = SqliteSaver(connection)
        graph = builder.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": output.name}, "recursion_limit": max(16, budget.limits.max_model_calls * 6 + 16)}
        final = graph.invoke({"run_id": output.name, "completed": [], "failed": False,
                              "ledger_path": str(output / "ledger.sqlite"), "budget": budget.report()}, config)
        interruptions = 0
        while final.get("__interrupt__"):
            interruptions += 1
            try:
                request = approval_request()
                decision = approval(request)
            except EXPECTED_ERRORS as error:
                on_error(error)
                decision = False
            final = graph.invoke(Command(resume=decision), config)
        count = sum(1 for _ in saver.list(config))
    return {"completed_nodes": final["completed"], "checkpoint_path": str(checkpoint_path),
            "checkpoints": count, "thread_id": output.name, "resumable": False,
            "approval_interruptions": interruptions, "resume_scope": "same-process approval only"}
