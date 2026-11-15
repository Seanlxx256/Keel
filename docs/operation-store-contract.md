# Atomic control-operation storage: first extraction

Implemented: `keel/operation_store.py`, called by `ControlService.operate` for
transactional control operations. SQLite remains the only backend. This does
not migrate model, MCP, read/write or acceptance broker receipts, budget SQL,
queue SQL, or other controller state to an interchangeable database.

## Required semantics

- Namespace comes from the server-authenticated principal, never a tenant ID
  claimed in the request body. Existing principal IDs remain globally unique.
- Matching principal, operation ID and request fingerprint return the committed
  response without reapplying business mutations.
- Changed input under an existing operation ID is denied.
- Authorization preparation runs before receipt lookup; controller replay logic
  retains active-lease checks for reservation/dispatch actions. A cached queue
  claim remains historical and cannot authorize another dispatch.
- Business mutations and the required receipt commit in the same transaction.
  A receipt-write failure rolls back the mutations and blocks further work.
- Explicit nonrecorded inspection paths do not create operation receipts.
- Preserve the existing `remote_operations` table, keys and serialized responses;
  opening an existing database does not clear or rewrite prior evidence.

The `OperationStore` protocol names the atomic operation, rather than exposing a
generic execute-SQL API to callers. However, current prepare/apply/replay callbacks
still receive the existing SQL transaction because the remaining controller
business logic has not been extracted. This is a transitional boundary: a
PostgreSQL backend cannot be dropped in without further transaction/SQL work.
Callbacks are trusted host code and must not execute providers, tools or sandbox
commands while holding the database transaction.

This extraction is not a general plugin loader. Backend registration is not
implemented. A subsequent [tenant identity slice](controller-tenancy.md) binds
multiple principals to one tenant and restricts scope/task ownership; optional
[aggregate quota checks](tenant-quotas.md) now constrain its scopes. Database
row-level policy and cross-node coordination remain separate work.

## Validation and next boundary

Eight new tests in `tests/test_operation_store.py` check receipt reuse after reopen,
principal namespace isolation, parameter mismatch, authorization on cache hit,
rollback on required receipt failure, legacy data compatibility, eight duplicate
requests over four concurrent threads, and inspection without receipt creation.
Together with existing control-service, task-queue and remote-checkpoint checks,
38 tests passed in 22.227s on 2026-11-15. Existing loopback HTTP fixtures exercise
the integrated service, not only the standalone adapter. No Docker/provider call,
real PostgreSQL backend, distributed load or multi-node test was run.

Next: extract business-level run/ownership and quota operations behind their own
transaction contracts, define explicit tenant membership and migration rules,
then implement and test a real service database adapter. Do not treat a new
Python protocol or SQLite concurrency test as distributed production readiness.
