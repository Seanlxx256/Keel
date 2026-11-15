# MCP cancellation and bounded service shutdown

Controller MCP calls now use a per-request `RequestControl` in the existing
`async_process_lifecycle.run_request` implementation. Cancellation is scoped to
that request's event-loop task and subprocess transports created by its SDK
connection. No arbitrary process ID, global event loop or unrelated process is
modified.

## Request evidence

Each new broker invocation has `lifecycle.json` beside its result/trace artifacts.
It records cancellation requests, whether the owned request finished, directly
observed SDK child PIDs/return codes, and lifecycle-storage errors. It never records
launch environment values or credentials. Lifecycle publication failure prevents
a successful broker response; cancellation is still attempted even if recording
the request failed.

The optional SDK hooks retain separate facts for dispatch attempted and result
returned. Cancelled calls without an established reply remain unknown, even if
the client transport and direct children have closed. Cancel is not permission
to retry or proof an external side effect was undone.

## Explicit cancellation

From the trusted host, another thread may use:

```python
session.cancel_pending_mcp()
```

This out-of-band call does not wait behind the long RPC's lock and does not
overwrite its pending request. The controller checks the exact principal/run/
original-operation binding. Response `cancel_requested` means only that a request
was made; `cancellation_confirmed` remains false. A restarted controller may report
`not_active_in_this_instance` while the persisted effect outcome stays unknown.

This API accepts no PID or external server address. Ordinary model/tool execution
does not resume automatically after cancellation.

## Service close

`service.close(timeout=10)` first stops admission for **both** acceptance and MCP
brokers, then shares its wait budget between them. MCP cancellation is scheduled
thread-safely on the owning loop. Request cleanup closes all owned transports and
allows up to three seconds to observe direct child exit, within the surrounding
shutdown observation; uncooperative SDK cleanup can outlive that observation and
must remain unconfirmed.

The control-service CLI preserves the existing filename
`<ready-file>.execution-shutdown.json`; schema version 2 now contains separate
`acceptance` and `mcp` component receipts. It reports admission-stop failures rather
than overwriting them with a later successful wait. Deadline/SIGINT/SIGTERM use
this managed shutdown path. Force-kill can bypass it.

Only the latest 32 finished MCP lifecycle summaries are included in a shutdown
receipt; per-operation files/control records remain the durable history. An
unconfirmed cleanup/storage counter prevents claiming clean shutdown after an
earlier failed lifecycle checkpoint.

## What this does not establish

- It does not certify an HTTP MCP server stopped processing an earlier request.
- Owned direct-child exit does not certify all descendants or OS resources closed.
- Older controller instances' effects are not cancelled by a new instance's memory.
- Source snapshots and `read_only` policy do not enforce OS/network isolation.
- Provider draining is now a [separate managed component](controller-provider-drain.md);
  it does not cancel remote generation or certify billing outcomes.
- Cancellation cannot forcefully interrupt arbitrary synchronous filesystem I/O.

Seven fixture contracts in `tests/test_mcp_lifecycle_control.py` passed, including
local cross-thread request cancellation. The official SDK memory/HTTP cancellation
integration also passed. Subprocess descendants and deployed shutdown remain unvalidated.


Current evidence and remaining boundaries: [2026-11-15 validation](development/governance-validation-20261115.md).
