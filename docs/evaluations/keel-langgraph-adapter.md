# LangGraph adapter: shared stages and checkpoint inspection

Keel now has native and optional StateGraph drivers over the same six phase
callbacks. Model Scout inspection and Planner generation were split into reusable
functions; the compatibility generate_plan entry point still exists. The runtime
keeps ownership of its ledger, workspace, role lifecycle, budgets, verification,
static/JUnit/mutation audit and final artifact creation. No parallel work items
or duplicate implementation of policy checks were introduced.

The graph has explicit Scout -> Planner -> Implementer -> Verifier -> Auditor
nodes, conditional edges to Critic for expected failures, and a Critic terminal
edge. Failed verification is audited before Critic. Unexpected exceptions retain
failed artifacts and propagate, as in native execution. The common sequential
phase runner and graph callbacks use the same error classifier. Baseline command
verification stays a distinct role phase inside Scout prerequisites.

SqliteSaver checkpoints contain run ID, node list, failure flag, ledger path and
budget snapshot. They intentionally exclude model histories, original source
bytes and live runtime handles. Budget state remains owned by the running process;
checkpoint state is not an authorization to reset or reconstruct it. There is no
resume API, approval interrupt, retry or time-travel entry point in this milestone.
Side-effect-safe restoration must be designed and tested before enabling one.

The LangGraph ledger connection allows framework worker threads only because the
graph is strictly sequential. This does not make Ledger a concurrent shared-store
API. The adapter checkpointer has a separate SQLite database and connection.

Official API references consulted:

- https://reference.langchain.com/python/langgraph/graph/state/StateGraph/compile
- https://reference.langchain.com/python/langgraph.checkpoint.sqlite/SqliteSaver
- https://reference.langchain.com/python/langgraph/types/interrupt

Validation on 2026-10-15:

- Native runtime tests: 9 passed; agent tests: 19 passed after stage extraction.
- Driver failure routing and missing-dependency preflight: 2 passed.
- Real-framework parity/checkpoint contents, protected-path failure routing and
  scripted agent/evidence-handoff execution: 3 tests provided, dependency-skipped.
- Package installation attempt failed with no available matching distribution in
  this restricted execution environment. Neither the base interpreter nor the
  existing user virtual environment had LangGraph installed at inspection time.
- CLI help, Python compilation and diff whitespace checks passed.

User validation (does not require Ollama or Docker):

```powershell
python -m pip install -e ".[langgraph]"
python -m unittest discover -s tests -p test_orchestration.py -v
```

Once these pass, an optional live run can select:

```powershell
python examples/run_keel_agent.py --orchestrator langgraph --backend docker --cpu --context-handoff --num-ctx 4096
```

Checkpoint inspection and real-framework execution remain unverified here; this
is not evidence of production persistence, safe resume, or framework speedup.


The full native regression completed 220 tests: 213 passed and 7 optional-dependency
skips. The subsequently added third real-framework test also remains skipped in
the local targeted suite. CI dependency installation now includes the LangGraph
extra so those tests execute where package access is available. Checkpoint files
are listed in the run artifact map when present.
