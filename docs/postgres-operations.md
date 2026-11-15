# Native PostgreSQL foundation: operation receipts only

Implementation status: optional native PostgreSQL unit of work and operation
receipt repository are present. Current ControlService still uses SQLite.
PostgreSQL run/budget/queue/tenant/broker repositories and controller migration
are not implemented. Real PostgreSQL integration is not yet validated here.

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

`tests/test_postgres_integration.py` contains five actual-server contracts:
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

After committing/pushing the workflow where GitHub can expose manual workflows,
select **Actions → PostgreSQL operation contracts → Run workflow**. This developer
turn prepared the file only: it did not commit, push, trigger Actions or start a
local/cloud PostgreSQL instance. The job remains unexecuted until triggered.
GitHub's service container is not a validation of Keel Sandbox isolation.

The final gate is `examples/verify_postgres_contracts.py`. It binds the read-only
preflight, successful watchdog, frozen implementation/test inputs and the actual
test inventory published by the shared runner. All five named native contract
cases must be present; unit-only runs, skipped/expected-failure cases, missing
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
  plan, original console and result. Manual workflow YAML and inline Python were
  statically checked; there is no GitHub execution result yet.
- Follow-up CI-readiness checks passed 45 local tests, including synthetic gate
  rejection cases and reporting/driver/SQLite regressions. Frozen evidence is in
  `.keel/production-reuse/postgres-ci-readiness-v2/`. This still contains no real
  PostgreSQL test execution; the manual CI remains pending.

## Primary technical references

- [Psycopg transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)
- [PostgreSQL READ COMMITTED and concurrent inserts](https://www.postgresql.org/docs/current/transaction-iso.html)
- [PostgreSQL INSERT/ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html)
- [GitHub PostgreSQL service-container setup](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers)
