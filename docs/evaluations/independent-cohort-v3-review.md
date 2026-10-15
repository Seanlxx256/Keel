# V3 metadata cohort and HTTPX dependency contrast

Collection: `.keel/independent-candidates/1e756e5c1f9b4b65a9f7240480c84a8c`.
All four repository collections completed. The fixed selected IDs are pytest
#11856, HTTPX #1588 and Requests #6757. No model execution or independent task
readiness follows from these metadata results. No selected ID is substituted.

## Curator metadata review

- pytest #11856 uses `pluginmanager.unblock` introduced in pluggy 1.4.0 instead
  of existing internal dictionary access. A version mention/new public API does
  not establish that old code fails with pluggy 1.4.0. Reproduction is unproven.
- Requests #6757 adds urllib3 1.26 testing/version-sensitive behavior. Its author
  explicitly states the newly enabled tests would still fail until an underlying
  issue is addressed. A complete reference-pass must not be assumed. Deferred
  pending suitable independent reproduction; not silently counted as a task.
- HTTPX #1588 adapts synchronous and asynchronous transport calls to HTTPcore
  0.13. The archived diff changes request entry points, argument names and
  response extension adaptation, alongside dependency bounds and tests. This
  provides a concrete API-migration hypothesis, still requiring execution.

Archived PR responses are curator-only. These observations are not model input
and do not establish unbiased task selection or absence from model training.

## HTTPX #1588 three-cell reproduction

Pinned base: `2d571046e15d3f4c4cbe5a68173cdf12e99cb3ca`.
Pinned gold: `d98e9e7ae7963a60ce8dc6a25cbe5f04c6438f4c`.
Primary provenance: https://github.com/encode/httpx/pull/1588
HTTPcore transition: https://github.com/encode/httpcore/pull/296

```powershell
python examples/reproduce_httpx_1588.py --collection .keel/independent-candidates/1e756e5c1f9b4b65a9f7240480c84a8c --build-images
```

This requires Docker Desktop and network for dependency images/Git snapshots.
It does not invoke a model. The script requires that #1588 was already selected
by the matching complete v3 policy/collection; it cannot promote a reserve.
Clean snapshots, Git first-parent identity and exact changed-file inventory are
checked. Output preserves the originating shortlist hash, probe and runner hash,
dependency versions, resolved image IDs and all partial execution records.

| Source | Dependency | Required result |
| --- | --- | --- |
| base | HTTPcore 0.12.3 | Four functional cases pass |
| base | HTTPcore 0.13.0 | Four cases fail at the removed request/arequest interfaces |
| gold | HTTPcore 0.13.0 | Same four functional cases pass |

Other dependencies are fixed identically. Each dependency-only image uses
Python 3.11-slim, exact package pins, `--no-deps` and `pip check`. The host
project is loaded from the pinned workspace, never an installed HTTPX wheel.
The Python base tag and wheels are not hash-locked for portable rebuilding.
Python 3.11 is a curator-selected environment; compatibility of these historical
dependency versions with that environment is not assumed until the old cell
passes. Unsupported environment results remain failed reproduction.

Acceptance uses the same loopback HTTP server for synchronous/asynchronous GET
and POST with status and response-body assertions. Docker's network-disabled
container still permits loopback; no external HTTP service is used. The pool
API is not mocked. Timeout, different dependency versions, missing cases,
unrelated exceptions or any failed positive control reject the probe.
The specific missing-interface check belongs to curator acceptance; it is not
a model-supplied replacement hint. TLS, proxies, HTTP/2, streaming and broader
exception mapping are outside this probe and need broader acceptance before
benchmark readiness.

Four offline tests cover the three-cell requirement, error/version/case checks,
probe syntax/design and parent/diff validation. The user subsequently executed
the probe successfully: reproduction `04d46e5f3a38498fb263307d3ded7f7d`
contains four passing base-old cases, four expected missing-interface failures
in base-new, and four passing gold-new cases. The exporter revalidated these
saved records; it did not rerun Docker inside the tool sandbox.
All artifacts remain `benchmark_ready: false`; no agent execution is wired yet.
This is curator-designed acceptance before inference, not a completed independent
model evaluation. Preserve the other cohort members and their dispositions.

## Task package boundary

`examples/package_httpx_transition.py` exports the successful reproduction:

```powershell
python examples/package_httpx_transition.py --reproduction .keel/upgradebench-reproduction/04d46e5f3a38498fb263307d3ded7f7d --output .keel/task-packages/httpx-1588-v1
```

The existing output directory cannot be overwritten. `task.json` is the only
declared model input: repository, base revision, dependency upgrade, behavioral
requirements and repository-wide Python source scope. It omits the PR body,
gold revision, patch and curator file localization. `acceptance.py` and
`manifest.json` are verifier-side artifacts. The manifest binds acceptance and
task hashes, resolved new image ID, expected versions/cases and originating
reproduction/shortlist receipts. It retains the base inventory for later
workspace verification, but no gold inventory or patch.

The saved package is `.keel/task-packages/httpx-1588-v1`; no model was called.
One package test exercises answer exclusion, hash binding, no overwrite and
rejection of an incomplete contrast. A future runner must actually enforce
these boundaries, verify hashes and source scope, preserve first-attempt
failures, and freeze model/budget/implementation before inference. A manifest
alone is not a security boundary or execution proof. This package does not
assert operator-unseen status and has not been frozen as an independent run.
