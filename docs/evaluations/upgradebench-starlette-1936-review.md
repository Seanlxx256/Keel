# Starlette #1936: compatibility candidate review

Status: selected-environment Docker probe reproduced; not a ready benchmark task.

## Recorded live result (2026-10-15)

User-executed artifact:
`.keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9`.
The saved executions were independently re-evaluated using `assess()` and passed
its evidence checks. Both base cases (`request`, `lifespan`) exited with the
expected `AttributeError` for missing `anyio.start_blocking_portal`; both gold
cases passed with exit zero. Neither execution timed out; stderr was empty.
Recorded dependency versions match the eight selected version pins exactly.

- Image ID: `sha256:47866eb38009a0bfa104f074399288e467fb98eeec5e04b016184352dcd62a4f`
- Probe SHA-256: `445ce86286be2c46ecde9cb7fa526b36c27ec3811f249287f8432dcb25100f8c`
- Environment: released AnyIO 4.0.0, not the original unreleased upstream commit.
- Outcome: one reproduced compatibility candidate; zero benchmark-ready tasks.

This establishes an actual API incompatibility in the chosen environment,
not merely an installation failure. Pending work: local Git range verification,
a frozen portable acceptance/environment bundle, leakage-reviewed agent task,
independent review, and a real Keel run. The two probe cases are not a full
upstream regression suite or two independent benchmark tasks.

## Runnable selected-environment probe

```powershell
python examples/reproduce_starlette_1936.py --build-image
```

This explicitly selects released AnyIO 4.0.0 rather than the author's unreleased
commit. It builds a Python 3.11 image with exact runtime package versions and
`pip check`, records the resolved image ID, prepares clean exact Git snapshots,
and runs the identical two-case request/lifespan probe on each revision. Both
containers use the same image ID, nonprivileged user, read-only mounts and no
network through the existing verifier runner. Image build and Git preparation
need network; acceptance does not. The build installs historical dependencies
only in this dedicated image; they are not project dependencies.

Image tags and package indexes are mutable inputs: version pins alone are not a
hash-locked environment. The resolved image ID identifies this run's environment;
it is not a portable image archive or independently reproducible image digest.
Run without `--build-image` to reuse the image; `--offline` additionally requires
cached snapshots. No agent/model is called.

Artifacts under `.keel/upgradebench-reproduction/<id>` contain image build and
inspect logs, base/gold executions, package versions and summary. `probe_passed`
requires both base cases to fail with the expected missing AnyIO API, both gold
cases to pass, exact dependency versions and case identities, and proper exit
codes. Timeouts, installation/import errors and unrelated test failures do not
count. `benchmark_ready` remains false even if this narrow probe succeeds.

The agent's initial execution could not access the Docker engine named pipe;
failure evidence is saved under
`.keel/upgradebench-reproduction/0a2776f8bc0c4b988a748f94f450d928`.
That initial attempt established no live result; the successful user run above
supersedes it. Two automated assessment tests
cover success and rejection of invalid evidence.

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

Clean exact snapshot checks, image build and base/gold execution are now recorded
for the selected environment; completed manual acceptance review and full Git
range verification remain pending. #2400 also enters the metadata review queue,
but its broader ASGI compatibility title alone does not establish an external
dependency-upgrade task.
