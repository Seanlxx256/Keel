# Stage-aware MCP failures and bounded alternative investigation

MCP failures now carry host-recorded stage information instead of only a generic
exception name. The stage comes from the actual client pipeline, not model text.

| Observation | Classification | Runtime handling |
|---|---|---|
| Host OS error at transport startup, before tool RPC | `McpTransportUnavailable` | Pause this configured server's aliases for the current role session; other authorized tools remain available |
| Parameter/schema or known protocol rejection | `McpToolError` with stage | Allow correction under existing permissions and budgets |
| Tool dispatch attempted, reply not established | `tool_outcome_unknown` | Preserve evidence and stop further agent actions pending reconciliation |
| Tool reply received, later result/cleanup failure | Stage-specific error | Do not pretend execution or cleanup succeeded; inspect the recorded pipeline/lifecycle |

`mcp-<server>.failure-<uuid>.json` records transport, stage, dispatch/reply flags,
safe exception type and numeric OS codes where present. Raw OS/server exception
strings and exception-group messages are not copied into the receipt. Failure to
save this required receipt aborts the action rather than silently falling back.

The controller MCP broker forwards the typed failure through authenticated RPC
without exposing its absolute artifact path. Local and remote AgentSession paths
therefore receive the same structured distinction. The model's next observation
includes the failure and, for startup unavailability, an explicit paused-tool list.
Pausing is scoped to one configured server and role session, not a permanent global
blacklist or a claim that every MCP transport is unavailable.

An alternative local read is ordinary authorized investigation, not proof the MCP
tool succeeded. Existing external-tool attempt/success policies and counters remain
in force; failed calls do not become completed requests. No code path grants new
filesystem/network privileges, reinstalls dependencies, changes Windows settings,
or silently retries an uncertain tool effect.

## Current restricted-host observation

The original official-SDK stdio fixture still fails in this execution context.
The preserved diagnostic at
`.keel/governance-regression-20261115/stdio-classification-a9a020759f26` contains:

```json
{
  "status": "environment_unavailable",
  "error_type": "McpTransportUnavailable",
  "failure": {
    "stage": "transport_start",
    "tool_dispatch_started": false,
    "reply_received": false,
    "transport": "stdio",
    "category": "transport_unavailable",
    "os_error": {"type": "PermissionError", "errno": 13, "winerror": 5}
  }
}
```

This does not prove no process ever started or no external side effect occurred;
it establishes that the tool RPC was not dispatched. The earlier bare-asyncio
reproduction independently locates the Windows pipe restriction. Operator terminal
permissions may differ. No OS access-control change was attempted.

## Verified scope

Eight new tests in `tests/test_mcp_failure_stages.py` cover classification, safe
receipt persistence, context isolation, same-server pausing, authorized fallback,
and stopping after unknown effects. A third official-SDK/loopback-HTTP integration
in `tests/test_mcp_broker_sdk.py` checks typed startup failure crosses the controller
boundary without invoking a tool or leaving a false pending effect.

The final focused group passed 89 tests without skips in 25.460 seconds:
`.keel/governance-regression-20261115/stage-closure-46626717af82`.
Existing MCP client regressions passed 9/10; the same real async stdio environment
error remains recorded at `mcp-client-stage-1990023139b9`. Tests were not changed
to skip that blocker. No Docker or paid model call was made, and no repair-score
or whole-repository CI success is claimed.

## Compare the operator shell without changing permissions

Run the same interpreter outside the restricted agent execution context:

```powershell
& 'D:\code\monocular_depth_estimation\.venv\Scripts\python.exe' D:\keel\examples\check_mcp_host.py --output D:\keel\.keel\governance-regression-20261115\host-controls-user-v1
```

Use a new output directory for each declared attempt; existing results are never
overwritten. No API key, configured MCP server, dependency install, Docker or
network request is used. Each fixed pipe control has an eight-second default
launcher timeout. The result sink is created and published before the first
control runs; each completed control is saved immediately.

If both controls pass in the operator shell while async fails in the agent
context, this isolates a context-dependent access difference, not a generally
broken Python installation. It still does not prove an actual MCP server works;
the original SDK fixture must then run in that shell. If async also fails there,
retain the numeric OS result before investigating Windows policy or security
software. This command neither identifies a specific policy nor changes one.

Actual restricted-host evidence: `host-controls-v1/report.json` under
`.keel/governance-regression-20261115/` records synchronous pipes OK and async
PermissionError errno 13 / WinError 5. Eleven related tests passed, including
absent parent publication and refusal to overwrite an earlier output. The prior
unified source snapshot remains immutable; these follow-up changes are not part
of that snapshot.

Operator-shell follow-up: `host-controls-user-v1/report.json` passed both pipe
controls with the same interpreter. `host-controls-comparison-v1.json` binds both
receipts by SHA-256. This supports a context-dependent access difference and
supersedes the pending operator-control status above. It does not identify the
specific restriction or certify SDK stdio; run `python -m unittest
tests.test_mcp_client -v` in that ordinary shell next. Preserve the original
restricted-context suite error rather than relabelling it as passed.

The operator subsequently reported `tests.test_mcp_client -v`: all 10 tests
passed in 4.337s in ordinary PowerShell with the same SDK interpreter. This
includes real Compass stdio, schema rejection, a subsequent successful call,
and SDK memory transport. Evidence source is the user-provided console output;
there is no separately captured developer-run log for this execution. The
restricted-context failure remains valid for that context. These results do
not constitute a new 249-test all-green run, Docker validation or full CI.
