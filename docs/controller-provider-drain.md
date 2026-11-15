# Provider-call draining and uncertain usage

The model proxy now participates in managed controller shutdown. This is bounded
draining, **not** provider-side cancellation or billing reconciliation.

## Admission, completion and uncertainty

Shutdown first prevents newly admitted provider calls. Existing admitted calls
are tracked through preparation, committed intent, provider call and settlement.
Requests already completed can still return their cached response without a paid
repeat. If shutdown is observed before entering the provider adapter, that request
records zero actual dispatch usage; it is not treated as a remotely cancelled call.

A call already at the provider is allowed to return within its configured provider
timeout. Known usage is settled normally, including a late response while shutdown
is waiting. On deadline, the controller does not close an unknown remote effect,
refund its reservation or issue a replacement request. Forced process exit can
still leave its durable intent unresolved.

The provider component receipt distinguishes:

- `current_calls_drained`: no call is still running in this controller instance.
- `persisted_inflight_records`: durable proxy intents still lacking completed outcomes.
- `unknown_usage_records`: usage remains unknown even if a local request returned.
- `active`: bounded-by-concurrency identifiers/phases; no prompts or completions.
- `unconfirmed_record_preview`: up to 32 unresolved operation/accounting references.

Unknown accounting can therefore leave `cleanup_unconfirmed` after all local calls
ended. That is accounting uncertainty, not proof a process or container remains
alive. These categories should stay separate in operational dashboards.

## Shared shutdown budget

`service.close(timeout=...)` stops acceptance, MCP and provider admission before
waiting on their component results. They share one budget. The CLI exposes:

```powershell
python -m keel.control_service --config service.json --host 127.0.0.1 --port 8788 --max-seconds 300 --shutdown-seconds 30 --ready-file service-ready.json
```

`--shutdown-seconds` defaults to 10 and is at most 30 seconds; required storage
operations have their own bounded waits. The existing schema-version-2 shutdown
receipt includes a `provider` component when configured. Current and historical
uncertainty is retained rather than converted into a clean financial outcome.

## Read-only request inspection

A trusted host can call `session.inspect_pending_model()` from another thread or
after restoring the client. It queries only the exact pending operation and leaves
that pending call untouched. Server authentication binds principal, run and target
operation. The result contains reserved/actual usage and operation status, not the
prompt, completion or credential. It does not authorize replay.

The controller reservation request ID is **not** a provider invoice identifier.
An authoritative provider usage/billing reconciliation adapter and explicit safe
unknown-usage resolution still remain separate work. Do not set unknown usage to
zero just to free budget or make shutdown appear clean.

## Validation boundary

Seven fixture contracts in `tests/test_provider_drain.py` passed. No actual
provider, shutdown under load or billing reconciliation has been executed. The provider adapter's
HTTP timeout is not proof remote generation/charging stopped at that instant.


Current evidence and remaining boundaries: [2026-11-15 validation](development/governance-validation-20261115.md).
