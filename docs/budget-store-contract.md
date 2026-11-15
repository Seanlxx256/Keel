# Business-level budget storage interface

Implemented in `keel/budget_store.py`, used by `governance.Session.reserve` and
`settle`. `ControlStore` supplies the current `SqliteBudgetStore`. Worker-facing
methods, remote RPCs and model-proxy usage remain unchanged. Only SQLite is
implemented; this is not a PostgreSQL adapter or a completed persistence plugin
system.

## Interface

`BudgetStore.reserve(grant, tokens, request_id=None)` performs run authorization,
scope/tenant admission, request intent and audit in one transaction. Duplicate
request IDs are rejected, not interpreted as authorization to repeat a call.

`BudgetStore.settle(grant, request_id, actual, outcome='completed')` commits known
or unknown usage and the audit outcome together. Known identical settlement is
idempotent; conflicting settlement is rejected. Unknown usage retains its hold.

`BudgetGrant` is an immutable host-created binding containing run ID, owner,
scope and lease duration. It is not a worker credential. The backend verifies
run owner and scope against persisted data. Reservations require an active run;
late usage settlement deliberately does not require or renew an active lease.

Unlike the earlier operation-receipt extraction, callers do not provide SQL
connections or SQL callbacks to these budget methods. Their public contract is
about budget behavior; SQL and transaction handling belong to the backend.

## Atomicity is part of the backend contract

Current SQLite repositories share `ControlStore.transaction`, including the
outer control-operation receipt transaction. Scope/tenant checks, counter changes,
request records and required audit therefore share the same commit boundary.
Audit failure must roll back both accounting and request state. The backend must
not invoke providers, tools or Sandbox operations while holding a transaction.

A future service-database implementation must migrate coordinated repositories
and their unit of work together. Pointing only the budget repository at PostgreSQL
while control receipts stay in SQLite creates a cross-database atomicity problem;
the Python protocol does not solve that. No runtime configuration currently
loads arbitrary repository classes or independently selects database backends.

Run creation/lifecycle now has a separate [RunStore interface](run-store-contract.md),
and the budget backend uses its ownership/active checks. Remaining SQLite coupling
includes schema initialization, backend queue/broker SQL, reporting and parts of control-operation callbacks. Those
must be extracted or ported before a full server database migration is usable.

## Contract tests

`tests/test_budget_store.py` covers duplicate reservation denial, known settlement
idempotence and conflict rejection, unknown/reopened accounting, late settlement
without reactivation, foreign owner/scope rejection, reserve/settle audit-failure
rollback, and actual Session delegation to the business interface.

Existing tenant quota tests also exercise the extracted path, including concurrent
admission across scopes and controller model-proxy denial before provider dispatch.
All providers in these fixtures are mocks. Test success is not provider billing
reconciliation, server-database correctness, distributed load or sandbox validation.

Validation on 2026-11-15: eight new budget contracts plus 13 tenant-quota
contracts passed; the frozen 20-module compatibility group passed 190 tests
without skips (73.162s unittest). Evidence under
`.keel/production-reuse/budget-store-v1/` retains the declared source/test archive,
original console, structured result and bounded watchdog. Inputs remained
unchanged. Prior baselines remain tied to their original implementation revisions.
