# Run authorization and lifecycle storage contract

Implemented in `keel/run_store.py`: immutable host `RunGrant`/`RunState`,
`RunStore` protocol and `SqliteRunStore`. ControlStore supplies the backend;
existing Session/remote APIs remain. `BudgetGrant` extends the shared run binding
for compatibility. SQLite is still the only backend. This is not a completed
distributed persistence system or service database adapter.

## Business operations

| Operation | Required behavior |
|---|---|
| create | Preserve established scope policy, create owner/run and required start audit atomically |
| get_bound | Check persisted run ID, owner and scope; inspect without renewing lease |
| require_active | Require current running state and unexpired deadline, then renew under host lease policy |
| finish | Require active authority, mark unfinished model requests unknown, retain holds and commit terminal state/audit |
| reconcile_expired | Scope-filtered detection of expired runs; mark unreachable/unknown, never replay or refund |
| bind_remote | Persist principal/task/grant-hash binding to a host-owned run |
| authorize_remote | Check principal, task, scope and current grant hash without granting or renewing execution |
| remote_task | Resolve task from persisted host run binding, never a caller-selected repository |

These interfaces accept business bindings, not SQL callback functions or caller
database connections. Run grants and owner IDs are trusted host internals, not
client bearer tokens. The controller still authenticates HTTP and computes the
current grant/policy fingerprint before remote authorization. Returned owner
material must not be added to worker-visible reports.

## Integrated transaction domain

ControlStore.begin/reconcile and Session active/finish paths use this interface.
Budget reserve uses the same active-run check; settlement uses ownership checking
without lease renewal. The controller uses the interface for remote binding and
deadline reads; model and acceptance brokers use it for timeout bounds, and the
read broker resolves its configured task through it.

Each method joins `ControlStore.transaction` when an outer transaction exists.
The current SQLite write transaction therefore combines remote begin, run row,
principal binding, start event and control operation receipt. A required receipt
failure cannot leave a new run/binding behind. Required start/finish/expiry audit
failure rolls back that operation's state changes.

Remote authorization alone is intentionally allowed after expiry for inspection
and late accounting. It does not reactivate work. A fresh dispatch still requires
`require_active` or the corresponding authorized state transition. Finished runs
retain unknown model holds; late trusted usage can settle them separately.

Lease time comes from the trusted current store clock and host policy. A future
multi-controller backend must choose an authoritative time/lease policy and test
clock skew and failure cases; worker timestamps are not execution permission.

## Preserved data and remaining coupling

The `governance_runs`, `governance_scopes`, `governance_requests` and
`remote_run_bindings` schemas remain compatible. Remote binding schema creation
moved into ControlStore initialization so the run backend has a consistent
schema even without a remote service. Existing rows are not rewritten.

This does not make it safe to put run storage in a different database from
budget, queue, audits and control receipts. All coordinated repositories must
share the same transaction/unit of work during a migration. Schema initialization,
reporting/inspection, tenant SQL, broker receipts and trusted write-adjudication
revocation still contain SQLite logic; there is no claim of complete SQL removal.
No configuration dynamically imports backend classes.

## Regression coverage

`tests/test_run_store.py` adds twelve contracts covering reopen/foreign identity,
remote grant checks, inspection without renewal, expired inspection without
dispatch authority, finish with unknown holds, scope-filtered expiry, required
audit rollback for start/finish/expiry, policy preservation, remote binding reopen,
and complete rollback when remote begin receipt publication fails. Existing
budget, tenant, queue, controller and broker fixtures exercise actual integration.
These do not certify Docker cleanup, a provider bill or multi-node execution.

The frozen 22-module compatibility group passed all 210 tests without skips on
2026-11-15 (73.482s unittest). Required result, original console, plan and source
archive remain under `.keel/production-reuse/run-store-v1/`; declared inputs were
unchanged. Earlier frozen runs remain evidence for their original revisions.
