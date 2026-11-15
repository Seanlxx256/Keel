# Task queue business-storage contract

Implemented in `keel/queue_store.py`: `QueueStore` protocol and
`SqliteQueueStore`. The existing `TaskQueue` in `keel/task_queue.py` is now a
stable facade delegating to this backend. ControlService, worker RPCs and the
trusted management CLI retain their existing public queue methods. SQLite is
the only implemented backend. This extraction does not add a distributed queue
or CPU/memory resource scheduler.

## Operations and authority

| Operation | Meaning and required rule |
|---|---|
| enqueue | Trusted producer binds item ID, principal, task ID and payload hash; changed-input reuse is denied |
| claim | Select at most one queued item, persist run/fence/lease and claim event atomically |
| transition | Start or record worker result only for the exact principal/task/run/fence and permitted state |
| status | Inspect only the authorized principal/task binding; apply expired-work classification |
| renew | Extend a current claim within the trusted run deadline; cannot revive expired/unknown work |
| requeue | Trusted operator decision for eligible uncertain/failed work, never automatic timeout retry |

These methods receive business identities and payloads, not SQL connections or
SQL callbacks. The controller authenticates the principal, checks the run grant
and active lease before worker queue actions. Direct backend calls are trusted
host APIs and are not a substitute for that authentication. No untrusted task
can choose a backend class or invoke an arbitrary imported plugin.

The current lease remains at most 300 seconds and no later than the supplied
trusted run deadline. Queue order remains the existing item-ID order; the new
interface does not introduce priority, tenant fairness, resource fit or scheduling
SLAs. Item IDs remain globally unique in the existing table schema.

## Required state and transaction semantics

- Concurrent claimers cannot each obtain the same queued item.
- A run cannot accumulate a second active/uncertain claim.
- Queue mutation, fence and queue event share a transaction.
- When invoked by the controller, queue state and the control RPC receipt share
  the same outer transaction. Failed required receipt publication rolls back
  the claim and its event.
- Matching completed control receipts are historical: controller replay of
  claim/start explicitly clears dispatch permission. Backend receipt reuse is
  not implemented as a second claim.
- Expiry means uncertain external effects; it must not automatically requeue
  work. Explicit operator requeue preserves history; the next claim advances
  the fence and old workers cannot update queue state.
- `reported_passed` is only a worker report, not independent acceptance. A
  supplied artifact hash does not prove the artifact exists or its tests passed.

Fencing queue state cannot stop an already-running process or reverse a remote
side effect. Trusted effect gateways and independently verified Sandbox lifecycle
remain necessary for strong distributed execution guarantees.

## Compatibility and future backends

The existing `control_tasks` and `control_task_events` schema, item payloads,
statuses and method arguments remain unchanged; reopening retains prior work.
The old `text` identifier helper is re-exported from `task_queue` for compatibility.
SQLite transaction/SQL implementation lives in the backend; the facade contains
no SQL. Trusted Python hosts can supply a backend object for contract testing,
but no administrator config loader selects alternative backend implementations.

Future PostgreSQL adaptation must coordinate run authorization, queue mutation,
audit and RPC receipts in the same database/unit of work. Replacing only the
queue object with a remote database while other repositories use SQLite is not
an atomic migration. Real backend transactions, concurrent consumers, restarts,
lost replies and failure recovery must be tested against the actual service.

## Validation

`tests/test_queue_store.py` adds eight contracts: concurrent claim once, rollback
on enqueue/claim audit failure, reopen and foreign-principal denial, expiry and
stale completion after requeue, one outstanding claim per run, facade delegation,
and rollback of claim/event on required controller receipt failure. The original
seven queue contracts remain in `tests/test_task_queue.py`, including historical
receipt behavior and worker-report authority. The focused group passed 15 tests.
These are local SQLite/thread/controller fixtures, not multi-node or load tests.

The frozen 21-module compatibility run passed 198 tests without skips on
2026-11-15 (78.320s unittest); required reports and unchanged input hashes are
preserved under `.keel/production-reuse/queue-store-v1/` with source archive and
original console. No Docker, paid provider or external database was invoked.
