"""Sequential StateGraph adapter; checkpoints are inspection records, not recovery."""
import sqlite3
from contextlib import closing
from typing import TypedDict

from ...orchestration import EXPECTED_ERRORS, PHASES


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


def execute_graph(stages, result, on_error, output, budget):
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
    builder.add_edge(START, "scout")
    for index, phase in enumerate(PHASES):
        following = PHASES[index + 1] if index + 1 < len(PHASES) else END
        builder.add_conditional_edges(phase, lambda state: "failed" if state["failed"] else "next",
                                      {"failed": "critic", "next": following})
    builder.add_edge("critic", END)
    checkpoint_path = output / "checkpoints.sqlite"
    with closing(sqlite3.connect(checkpoint_path, check_same_thread=False)) as connection:
        saver = SqliteSaver(connection)
        graph = builder.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": output.name}, "recursion_limit": 16}
        final = graph.invoke({"run_id": output.name, "completed": [], "failed": False,
                              "ledger_path": str(output / "ledger.sqlite"), "budget": budget.report()}, config)
        count = sum(1 for _ in saver.list(config))
    return {"completed_nodes": final["completed"], "checkpoint_path": str(checkpoint_path),
            "checkpoints": count, "thread_id": output.name, "resumable": False}
