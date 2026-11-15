# MCP host preflight

Tasks may opt in before orchestration and before the first model request:

```json
"mcp_preflight": {"mode": "strict", "timeout_seconds": 8}
```

Omitting the field preserves existing behavior. Timeout must be finite, positive,
and at most 15 seconds. The remaining task wall-clock budget bounds each probe.
`strict` stops with `environment_blocked` when capability is unavailable or a
required host is not checked. `advisory` records the result and continues; it
does not grant new permissions, certify an external tool, or erase a failure.

The local check verifies MCP/jsonschema dependency availability and, for stdio,
launches a fixed short Python asyncio pipe diagnostic in the current interpreter.
It never starts the configured server, sends credentials, or calls a model/tool.
The shared implementation is `keel/ipc.py`; task integration is in
`keel/mcp_preflight.py` and `keel/runtime.py`.

The report is saved as `mcp-preflight.json`, included in the run result, and
recorded in the trace. Required report-write failures are not ignored. A failed
check occurs before code edits. The advisory report may remain unavailable even
when a task completes without using MCP.

Limits: this is host capability checking, not MCP server readiness or semantic
acceptance. HTTP MCP endpoint access is explicitly untested. Controller-routed
MCP is checked by an authenticated RPC on the controller interpreter, against
operator-owned server configuration. The controller persists a JSON receipt and
database outcome bound to principal, run and policy. Each run retains one check;
repeated matching requests return that historical result, not a fresh check.
Changed timeout/policy requires a new run. An unfinished receipt is not replayed.
Recovery-only clients can reconcile an existing request but cannot start a new
probe. New admission stops with the broker; an already admitted bounded probe
is not included in the MCP tool-process drain certification.
No automatic dependency installation, permission changes, or
server fallback is performed. This cannot certify process-tree isolation.

Regression contracts: `tests/test_mcp_preflight.py`. See the development learning
journal for actual execution evidence and retained environment failures.
