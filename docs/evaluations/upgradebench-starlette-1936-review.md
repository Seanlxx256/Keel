# Starlette #1936: compatibility candidate review

Status: preliminary curator review; not a ready benchmark task.

## Archived evidence

- Repository: `kludex/starlette`; PR: https://github.com/Kludex/starlette/pull/1936
- Base (merged commit first parent): `fbab16a2b114321c1694788b21113bbba8943778`
- Gold merged commit: `a45027209ae4c033007d827a37bbbee53550973a`
- Changed file: `starlette/testclient.py`.
- Source archive: `.keel/upgradebench-mining/0b9336d864ae470e8a9ac5cd08d8a092`.
- Schema v3 replay: `.keel/upgradebench-mining/4c363ce8c3e04fec820df75f7022b97d`.

The archived PR description identifies an unreleased AnyIO change at commit
`9f97cd7bb5f59f79f1bcda64230ab2127e79935a`. This is an upstream dependency
revision cited by the author, not a locally verified reproducible dependency.
The archived patch imports `anyio.from_thread` and replaces two calls to
`anyio.start_blocking_portal` with `anyio.from_thread.start_blocking_portal`.
This is a concrete API-location change, making the PR worth reproducing.

Strict screening still rejects it: fewer than three changed files and no
dependency manifest change. The separate compatibility pool retains it for
review without changing strict eligibility or benchmark denominators.

## Required reproduction gate

1. Verify the local base-to-gold Git range and changed paths against receipts.
2. Resolve the cited AnyIO commit, Python constraints and a complete frozen
   dependency environment. Do not substitute current package versions silently.
3. Build a trusted acceptance bundle exercising TestClient lifespan/portal
   behavior, with the same tests and dependencies for base and gold.
4. Run both revisions in Docker; require an actual API incompatibility failure
   on base and passing acceptance on gold. Installation errors are not evidence.
5. Record test identities, execution metadata, image identity and logs. Review
   agent-visible instructions separately so the gold patch stays curator-only.

No checkout verification, image build, base/gold execution or completed manual
acceptance review is claimed here. #2400 also enters the metadata review queue,
but its broader ASGI compatibility title alone does not establish an external
dependency-upgrade task.
