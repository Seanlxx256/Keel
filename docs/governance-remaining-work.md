# Governance implementation and remaining work

This inventory separates source implementation from environment validation. Skipping
Docker/WSL validation does not establish a sandbox security result.

## Implemented interfaces

- Same-host transactional quota reservations, uncertain usage retention, expiring
  leases, role tool policy and required audit writes: `keel/governance.py`.
- Authenticated control service, server-owned grants, atomic RPC receipts and
  bounded HTTP concurrency: `keel/control_service.py`.
- Remote client, uncertain RPC reconciliation and optional trusted-host durable
  client checkpoints: `keel/remote_governance.py`.
- Real two-container validation runner with explicit unavailable results:
  `keel/docker_isolation.py`. Actual container validation remains pending.
- Controller-owned task queue with leases, fencing, uncertain expiry and explicit
  operator requeue: `keel/task_queue.py`, [protocol](control-task-queue.md).
- Single-attempt supervised Runtime worker: `keel/queue_worker.py`,
  [configuration and boundaries](queue-worker.md). Lifecycle observer is a trusted
  parent process; kernel/network supervision and live validation remain pending.
- Controller-owned model execution and proxy-only principal policy:
  `keel/model_proxy.py`, [setup](controller-model-proxy.md). General command/MCP
  execution and deployment egress enforcement remain separate work.
- Controller-executed read-only tools with explicit catalogs and source-checked
  Runtime evidence import: `keel/tool_broker.py`, [setup](controller-read-broker.md).
- Controller exact replacement with source preconditions and durable uncertain-path
  exclusion: `keel/write_broker.py`, [setup](controller-write-broker.md).
- Trusted local uncertain-write adjudication with same-host advisory locking,
  source-bound plans and original-run revocation: `examples/resolve_controller_write.py`.
- Fixed asynchronous Docker/JUnit acceptance and hash-bound paged results:
  `keel/execution_broker.py`, [setup](controller-execution-broker.md).
- Bounded acceptance shutdown and labelled-container inspection/removal:
  `keel/container_receipts.py`, [scope](controller-execution-cleanup.md).
- Controller-owned navigation MCP calls and Runtime routing:
  `keel/mcp_broker.py`, [scope](controller-mcp-broker.md).
- Scoped MCP request cancellation, direct-child receipts and shared managed shutdown:
  `keel/async_process_lifecycle.py`, [scope](controller-mcp-lifecycle.md).
- Provider admission stop, bounded draining and read-only uncertain-call inspection:
  `keel/model_proxy.py`, [scope](controller-provider-drain.md).
- Stage-aware MCP failure receipts and role-session alternative-tool strategy:
  `keel/mcp_client.py`, `keel/agents.py`, [scope](mcp-transport-failures.md).
- Opt-in zero-model local/controller host preflight, with durable controller
  outcomes and no implicit replay: [scope](mcp-preflight.md).

## Durable remote client recovery

Add an optional `state_path` to the remote `governance` object. Use a dedicated,
trusted-host directory outside the task repository; never mount it in untrusted
containers. Each new run needs a new file. Existing files are never silently
overwritten by `begin`.

```python
from keel.remote_governance import RemoteSession

config = {
    'endpoint': 'http://127.0.0.1:8788',
    'token_env': 'KEEL_WORKER_CONTROL_TOKEN',
    'task_id': 'task-a',
    'state_path': 'D:/KeelControl/client/task-a-attempt-1.json',
}
# Normal runtime initializes the client; the credential comes from the environment.
# After a crash, an operator restores control state without rerunning the task.
session = RemoteSession.recover(config)
if session.pending is not None:
    session.reconcile_pending()  # Same RPC identity, never a provider/tool replay.
report = session.report()
session.finish('failed')  # Close the interrupted run after inspection.
```

An intent is published before dispatch; confirmed replies clear it. Failure to
publish blocks further operations. Restored clients permit inspection and closure,
not new reservations, tools or edits. A recovered reservation is not permission to
repeat its external action. The controller still authenticates the current
credential and checks its binding. The checkpoint stores no bearer token, but
event payloads may contain sensitive task data; protect it accordingly.

This is atomic file replacement for process-crash recovery, not power-loss
durability certification, signed tamper-proof storage, multi-writer coordination,
or full workspace/model conversation resume. Only one trusted process may own a
checkpoint. Restoring a session does not prove any earlier external action ran.

An explicit recovery CLI is also available. This command reconciles control RPCs
only; it never starts a provider, tool or Docker container:

```powershell
python -m examples.recover_remote_governance --config task.json --reconcile --close-failed
```

Without `--reconcile`, a pending request is reported without contacting the
controller. The required checkpoint file is updated even during recovery; this
command is therefore not a read-only forensic viewer. Preserve a copy first if
immutable forensic evidence is required.

## Not implemented yet

| Capability | Required next implementation | Evidence still needed |
|---|---|---|
| Automatic diagnosis of uncertain effects | Keep implemented operator adjudication explicit; broader evidence collection and independent supervision remain | Partial write, crash and conflicting source tests |
| Provider billing reconciliation | Authoritative usage lookup and explicit unknown-usage adjudication; no assumed zero | Lost-response, late-usage and conflicting billing tests |
| Deployment enforcement | Independent external supervision and credential/network isolation | Model/tool bypass, real shutdown/daemon cleanup and lost-response tests |
| Independent sandbox supervisor | External lifecycle observer and validated event provenance | Crash, kill and disconnect injection |
| Ray/Kubernetes deployment | Worker lifecycle adapter, trusted-host/agent boundary, deployment policies | Real cluster and cross-node isolation |
| Cluster worker execution | Adapt the single-host supervised worker to deployment lifecycle and external node monitoring | Duplicate delivery, lease loss and real worker crashes |
| Multi-node persistence | Transactional server database adapter and migrations | Contention, restart and backup/restore |
| Large artifact service | Authorized object identity and content-addressed manifests | Upload interruption and tenant isolation |
| Search/telemetry backends | Derived indexes and bounded optional delivery | Telemetry outages must not erase required audit |
| Production ingress | Certificate rotation, rate limiting and secret lifecycle | Real TLS/network and load validation |

These are separate deliverables, not dependencies to install merely to claim
feature completeness. SQLite coordination currently remains single-host.

## Validation status for this change

Non-Docker validation resumed on 2026-11-15. The final new regression/integration
group passed 95 tests without skips. The existing compatibility group passed 117
of 118; its remaining official-SDK stdio error was independently reproduced as
Windows async-pipe access denial. The failure remains recorded, not reclassified
as a pass. See the [full evidence and boundaries](development/governance-validation-20261115.md).

Actual Docker, provider billing, distributed deployment and production performance
remain unvalidated. This focused check does not replace full CI or official task grading.

The subsequent [transport-stage checks](mcp-transport-failures.md) passed 89 related
tests. The physical async stdio permission blocker remains unresolved.

The consolidated 27-module baseline attempted 249 tests: 248 passed, one retained
MCP stdio environment error, no skips. Source/test bytes were unchanged during
execution and an implementation/test snapshot was archived. The ad hoc runner
failed to publish its final JSON because its result directory was absent;
`unified-v1/assessment.json` explicitly derives counts from the original log and
preserves that separate publication failure. This is a frozen diagnostic
baseline, not a green release. See the validation report for evidence locations.

Operator-shell follow-up: the user reported all 10 MCP client tests passing in
4.337s, including the real Compass SDK stdio case. Same-interpreter pipe controls
also passed there. The remaining stdio error is context-dependent on the agent
execution host; no Windows-wide repair was performed or shown necessary.
This targeted user-run result does not replace the retained consolidated run.
