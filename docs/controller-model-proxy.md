# Controller-owned model proxy

The optional proxy moves provider execution and usage accounting into the existing
authenticated controller. Worker hosts receive a model alias and control credential,
not the provider API key. Runtime's ordinary model interface remains unchanged.

## Service configuration

Add a `model_proxy` object to the existing service configuration:

```json
{
  "model_proxy": {
    "models": {
      "repair": {
        "provider": "openai-compatible",
        "name": "REPLACE_WITH_PROVIDER_MODEL",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "KEEL_CONTROLLER_PROVIDER_KEY"
      }
    },
    "max_output": 8192,
    "timeout_seconds": 20,
    "max_concurrent": 2
  }
}
```

This fragment is not a complete service config: retain its path, scopes and
principals. Add `"models": ["repair"]` and `"require_model_proxy": true` to the
specific principal. With that flag, direct worker `reserve` and `settle` RPCs are
denied; provider requests and usage settlements belong to the controller.
Server provider credentials are locally checked during startup, without a paid
request. Secret values are never placed in service JSON or client checkpoints.

The trusted provider settings support existing `openai-compatible` and `ollama`
adapters. Clients cannot choose a provider URL, credential name or model settings.
Changes to granted proxy policy invalidate existing run bindings, requiring an
explicit new run rather than silently changing an in-flight model configuration.

## Runtime configuration

```json
{
  "model": {"provider": "control-proxy", "alias": "repair"},
  "governance": {
    "endpoint": "http://127.0.0.1:8788",
    "token_env": "KEEL_WORKER_CONTROL_TOKEN",
    "task_id": "task-a",
    "timeout_seconds": 3
  }
}
```

Merge the fragment into a complete task. The existing Runtime governance binder
attaches the remote session to the proxy model. It does not wrap the proxy in a
second reservation layer. Standalone `from_config` without governance binding
cannot dispatch. In a supervised queue worker, omit task governance as usual;
the worker supplies it. Do not add the controller provider key to `allow_env`.

## Commit, dispatch and reconciliation

1. Authenticate and check the principal's fixed model alias grant.
2. Validate request, check active run and atomically reserve scope quota alongside
   a durable proxy operation intent.
3. Commit before calling the provider. Network work holds no SQLite transaction.
4. Persist usage settlement and the cached response in a single transaction.

The model's provider call is attempted once. The same operation ID with changed
input is rejected. A completed duplicate returns its cached reply without another
provider call. An in-flight record after a crash/response loss remains uncertain;
no repeat call is authorized. Known failure usage is recorded; missing usage keeps
the reservation. Worker usage claims cannot refund proxy calls.

The recovered RemoteSession can reconcile exactly that saved RPC. Its ordinary
recovery-only restriction still prevents new model calls. A cached model response
is historical output, not permission to replay downstream edits or tools.

## Bounds and status

Provider timeout is server-capped, default 20 seconds, maximum 25. Client response
headroom is bounded at 30 seconds and clamped by the local remaining budget.
Requests remain under the existing 128 KiB control-transport cap; responses are
limited to 240,000 bytes. Oversized data is rejected, never silently truncated.
These are prototype transport limits, not claims of a model context-window size.
Concurrency defaults to two provider calls; use enough HTTP workers to leave
capacity for lease renewals and inspections. Capacity rejection dispatches nothing.

The reservation estimate remains serialized-input bytes plus requested output,
not exact provider tokenization. Accounting is from the controller's provider
adapter, not independent billing reconciliation. A provider overrun is recorded
and reported as an error. This implementation does not promise a strict financial
cost ceiling independent of provider behavior.

## Enforcement boundary

This implements a controller-owned **model** execution path and a server-side
proxy-only RPC policy. Full mandatory routing additionally requires withholding
provider secrets and restricting outbound network access in deployment. A host
with arbitrary shell, credentials and egress can still bypass the service.
Controller-owned read and exact-replacement paths are now available through the
[read broker](controller-read-broker.md) and [write broker](controller-write-broker.md).
Controller MCP navigation and fixed Docker acceptance have separate broker
paths. General host commands and real network/credential bypass enforcement remain
outside this model proxy guarantee.
This is not a production internet-facing API gateway.

The proxy also supports [bounded provider draining](controller-provider-drain.md)
on controller shutdown; this never equates a lost connection with zero usage.

Eleven fixture regression contracts in `tests/test_model_proxy.py` passed.
Real provider requests, Docker and production performance remain unvalidated.


Current evidence and remaining boundaries: [2026-11-15 validation](development/governance-validation-20261115.md).
