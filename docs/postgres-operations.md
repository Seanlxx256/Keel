# Native PostgreSQL foundation: operation receipts only

Implementation status: optional native PostgreSQL unit of work and operation
receipt repository are present. Current ControlService still uses SQLite.
PostgreSQL run/budget/queue/tenant/broker repositories and controller migration
are not implemented. The manual real-PostgreSQL GitHub Actions artifact
`postgres-operation-contracts-43699827320-1` has been inspected in the workspace;
its commit identity, test inventory, reports and declared artifact hashes match.

## What is implemented

`PostgresUnitOfWork` uses psycopg 3 directly, native `%s` parameters and explicit
READ COMMITTED transactions. Nested repository calls join one thread-local
connection rather than committing independently. Connection, statement and lock
timeouts are configured; they do not impose a total deadline on arbitrary trusted
Python callbacks. Use the shared bounded runner for the overall test deadline.
Connection/transaction/cleanup failures do not trigger automatic retries or leak
raw DSN/server error messages. Unknown outcomes require original-ID reconciliation.

`PostgresOperationStore` implements the operation interface using a database unique
key `(principal, operation_id)`. A pending row is inserted with ON CONFLICT DO
NOTHING; a subsequent locked read coordinates contenders before business apply.
Both the business SQL and completed response commit together. A duplicate reads
the response; changed input is denied. Pending/corrupt receipts do not authorize
blind replay. Prepare/replay can run again and must not cause external effects.
Only trusted transactional SQL callbacks are supported, not model/tool dispatch.

Schema setup uses an explicit contiguous migration ledger with checksums,
version/name drift rejection, and a transaction-scoped PostgreSQL advisory lock.
Repository construction still does not migrate. The initial
`operation-receipts-v1` migration is idempotent; later changes must append a new
version rather than rewrite an applied migration. This is a small migration
mechanism, not a general online migration or rollback framework.

PostgreSQL and SQLite share request-envelope validation. Their SQL is separate;
no SQL-string substitution adapter is used. The PostgreSQL repository owns a
different transaction domain and cannot be silently attached to the SQLite
controller. Moving the remaining coordinated repositories is still necessary.

## Dependencies, preflight and migration boundaries

Optional dependency: project extra `postgres` (`psycopg[binary]>=3.2,<4`). It is
not installed automatically. Credentials are obtained from a named environment
variable on the executing host; never paste a DSN/password into chat or commit it.

Read-only preflight, after configuring the environment locally:

```powershell
python examples/check_postgres_connection.py --dsn-env KEEL_POSTGRES_DSN --output .keel/postgres-check-user-v1
```

Use a fresh output directory. The script establishes its required report before
connecting, reports driver/DSN presence without values, and executes a read-only
version/query check. It does not create tables or certify persistence behavior.
For a strict overall deadline, invoke through the shared bounded exploration plan.

Repository construction does not create tables. Explicit `initialize_schema()`
creates `public.keel_operation_receipts_v1` in the selected database. This is an
initial schema operation, not a versioned migration engine or SQLite data import.
Use a dedicated test database before attempting real contracts. There is no
automatic destructive cleanup, quota migration or controller backend switch.

## Real integration contracts

`tests/test_postgres_integration.py` contains actual-server contracts:
concurrent duplicates produce one SQL effect, reopen uses a completed receipt,
callback failure rolls back intent and business data, principal namespaces remain
separate, and changed input cannot reapply. To enable them explicitly:

- Configure `KEEL_TEST_POSTGRES_DSN` locally to a dedicated test database.
- Set `KEEL_TEST_POSTGRES_ALLOW_SCHEMA=yes` to permit test table creation.
- Run `python -m unittest tests.test_postgres_integration -v` under a time bound.

Tests create `public.keel_operation_receipts_v1` and
`public.keel_operation_test_effects_v1`; fixture rows use unique IDs and are retained.
They never drop or truncate tables. Without opt-in they are skipped, not counted
as database correctness evidence. With opt-in, a missing driver/service is an
error, not silently converted into a skip or a mock success.

## Manual GitHub Actions path when local Docker is unavailable

`.github/workflows/postgres-contracts.yml` is manual-only (`workflow_dispatch`).
It uses an Ubuntu runner with a disposable PostgreSQL 17 service, installs the
optional driver, runs read-only preflight, freezes declared inputs, and invokes
the shared watchdog (120s test budget). It rejects skipped database tests and
uploads scoped reports/logs even after failure. Fixture credentials are only for
the disposable CI service and are not deployment credentials.

The first manual run is retained as
`postgres-operation-contracts-43699827320-1/`: it ran 18/18 tests against
PostgreSQL 17.12, including all five initial integration cases. The service
container is not a validation of Keel Sandbox isolation. The current working
revision extends this contract with migration idempotency; that new case still
needs a fresh Actions run after commit.

The final gate is `examples/verify_postgres_contracts.py`. It binds the read-only
preflight, successful watchdog, frozen implementation/test inputs and the actual
test inventory published by the shared runner. All named native contract cases
must be present; unit-only runs, skipped/expected-failure cases, missing
test-source hashes and changed code are rejected. It publishes `acceptance.json`
with evidence hashes and preserves prior verdicts. This is trusted CI evidence
checking, not cryptographic attestation against a compromised runner or proof
that arbitrary test bodies are correct.

## Current evidence

- 13 driver-contract tests passed using explicit connection fixtures. These check
  control flow and error handling, not PostgreSQL SQL/locking/commit semantics.
- The frozen local group passed 31 tests: those fixtures plus existing SQLite
  operation and transaction-domain regressions. No skipped tests in this declared
  local group; real integration tests were separately unavailable (five skipped).
- `.keel/production-reuse/postgres-preflight-v1/report.json` records no driver and
  no DSN in the current execution environment, zero model calls/migrations.
- `.keel/production-reuse/postgres-operations-v1/` retains source/test archive,
  plan, original console and result from the earlier local run. Manual workflow
  YAML and inline Python were statically checked at that time.
- Follow-up CI-readiness checks passed 45 local tests, including synthetic gate
  rejection cases and reporting/driver/SQLite regressions. Frozen evidence is in
  `.keel/production-reuse/postgres-ci-readiness-v2/`. These local checks are not
  real PostgreSQL execution.
- `postgres-operation-contracts-43699827320-1/acceptance.json` reports `passed`,
  commit `734ff2aeb92067875b1bd8df48e10c21a9f74d1a`, PostgreSQL `17.12`, psycopg
  `3.3.9`, and 18/18 total tests with no failures, errors, skips or expected
  failures. The 5 required native integration cases all appear in the inventory;
  the other 13 are driver-contract tests. Preflight and watchdog both passed, the
  source inputs were unchanged, and recomputation matched all six artifact
  SHA-256 entries. This verifies the operation-receipt backend contract only;
  it is not a full controller migration or deployment qualification.
- Current uncommitted migration work adds a checksummed schema ledger and a sixth
  real-server contract for idempotent migration/reopen with existing receipts.
  Local unit/contract-gate checks passed 28/28; the new PostgreSQL-specific
  contract has not yet been run against a real server. The prior 18-test artifact
  remains valid for the earlier commit and is not overwritten.

## Primary technical references

- [Psycopg transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)
- [PostgreSQL READ COMMITTED and concurrent inserts](https://www.postgresql.org/docs/current/transaction-iso.html)
- [PostgreSQL INSERT/ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html)
- [GitHub PostgreSQL service-container setup](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers)
