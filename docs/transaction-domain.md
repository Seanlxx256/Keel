# Shared persistence transaction-domain guard

Implemented: `transaction_domain.require_shared_domain`, an in-process trusted-host
composition guard. It catches accidentally mixed transaction managers before
business execution. It is not a database backend, distributed transaction system,
security sandbox, or proof that a third-party plugin honestly implements atomicity.

## Why matching database paths are insufficient

Suppose a control operation opens transaction A and writes its receipt only after
budget reservation. If the budget backend independently opens transaction B and
commits it, failure of A cannot roll back B. With SQLite the second writer may
instead block on A's lock. Neither outcome becomes safe simply because both
connections name the same file.

Current ControlStore owns both an identity token and its thread-local nested
transaction manager. Built-in run, budget, queue and operation repositories
declare that manager's `transaction_domain`. Compatibility requires object
identity, not a matching path, string or equality method. A separately constructed
ControlStore for the same file deliberately has a different domain.

Independent processes/controllers may each own their internally consistent local
repository bundle. The token is not a cross-process database lock or persistent
identity; it does not coordinate those processes or certify their concurrency.

## Enforcement points

- ControlStore transaction entry checks the configured budget/run repositories.
- Session budget methods and finish, plus local begin/reconciliation, check before
  delegating to a repository that could otherwise open another manager's transaction.
- TaskQueue checks a supplied backend at construction and before each delegated
  method, so replacing a backend later is not silently accepted.
- ControlService checks operation receipts and queue as well as run/budget storage
  before routing an RPC, including broker endpoints.
- Missing/mismatched domains raise required `GovernanceUnavailable`; raw backend
  property exception messages are not relayed.

This guard rejects mixed composition even for ordinary RPC inspection. Trusted
operator read-only database inspection remains a separate path; preserving access
to authoritative evidence does not authorize new work with a broken bundle.

## Backend responsibilities and limitations

Backend classes are trusted code. A class that returns the right token but opens
its own connection can lie to this guard. Contract tests, receipt/audit rollback
injection and real database integration are still required. The token is not
accepted from worker JSON and does not grant filesystem/network authority.
Test doubles must explicitly declare their intended domain; doing that does not
make their behavior production-certified.

No concurrent hot replacement of backend bundles is supported. Select and validate
a coherent bundle before accepting work; configuration changes and migrations
need explicit lifecycle handling. All repositories participating in an atomic
operation must join the same unit of work. Tenant and broker SQL not yet abstracted
still uses the existing ControlStore, and must migrate with that bundle.

## Service database status

This turn found neither `psycopg` nor `psycopg2` in the existing SDK interpreter,
and `psql` was not on the shell PATH. No installation, database connection or
credential lookup was attempted. This does not prove a remote PostgreSQL service
is unavailable; no usable service/database integration has been established.
Docker remains deferred. A future PostgreSQL adapter must be tested with a real
service and its transaction semantics, not declared successful using mocks.

## Tests

`tests/test_transaction_domain.py` covers one shared nested connection, same-path
different-manager rejection, missing/throwing domain metadata, and rejection
before reserve/create/finish/queue/control callbacks dispatch. Existing rollback
contracts continue to check actual state atomicity, independently of the token.

Validation on 2026-11-15: 38 focused tests passed, followed by a frozen 23-module
compatibility group of 220 tests, all passed without skips (73.368s unittest,
80.047s watchdog). Required artifacts and unchanged source/test hashes are
retained in `.keel/production-reuse/transaction-domain-v1/`. No external database,
Docker or paid provider call was dispatched.
