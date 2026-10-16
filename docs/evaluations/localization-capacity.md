# Optional localization capacity check

2026-10-16, offline only. Artifacts: `.keel/localization-capacity-v1/`.
No provider, credentials, network or Docker was used. Base snapshots were read
through Workspace; before/after source inventories matched. This is input
capacity measurement, not model localization or repair performance.

| Base repository | Outcome at 12,000 input bytes | Last structure size | Source files scanned | Tool calls |
| --- | --- | ---: | ---: | ---: |
| HTTPX 1588 | Structure overflow before inference | 13,926 bytes | 11 | 12 |
| Starlette 1936 | Structure overflow before inference | 12,268 bytes | 21 | 22 |
| Flask-WTF 565 | First localization request fits | 3,128 bytes | 15 | 16 |

For Flask-WTF the full structured localization request is 4,294 bytes under a
generic measurement goal. A real task goal changes this size. HTTPX/Starlette
sizes are the last partial map at early termination, not their full repository
map sizes. Source enumeration is deterministic, but path order does not imply
relevance. The file count excludes protected write targets and non-Python files.

The measurement uses a non-network sentinel at the provider boundary. A sentinel
request is not a real model invocation; `new_model_calls` is zero. Existing
Budget preflight may increment its attempted-call counter before the sentinel,
so that internal counter must not be presented as a billed provider request.
Tool accounting uses real host reads/listing. Snapshot byte counts include
repeated fingerprint work and are not distinct source bytes or physical I/O.

Reproduce with a new output directory:

```powershell
python examples/measure_localization.py --repo .keel/independent-snapshots/encode--httpx/2d571046e15d3f4c4cbe5a68173cdf12e99cb3ca --repo .keel/upgradebench-snapshots/kludex--starlette/fbab16a2b114321c1694788b21113bbba8943778 --repo .keel/upgradebench-snapshots/pallets-eco--flask-wtf/2d80102a5d85ef5cae3a3994ca4cb75679165ba2 --output .keel/localization-capacity-v1
```

## Design decision

Do not run paid HTTPX localization with this version and do not increase the
default budget merely to fit the whole map. Next prototype should separate:

1. bounded source path/directory selection;
2. symbols/anchors from selected files only;
3. existing exact patch proposal and independent verifier/auditor.

This adds a localization request and changes optional-path costs, which must be
recorded in any comparison. A source-path list can itself exceed a cap; fail or
use explicit hierarchical navigation rather than silently excluding later files.
Selected source context can still overflow and must remain bounded. No default
architecture replacement, index replacement or shell permission expansion is
required. The existing mode remains an experimental prototype until those limits
and tests are addressed.

## V2 file-first request measurement

The optional mode now selects files from paths before reading selected symbols.
The same non-network preflight was repeated to `.keel/localization-capacity-v2/`:

| Repository | First request bytes | Tool requests before model boundary |
| --- | ---: | ---: |
| HTTPX | 1,079 | 1 |
| Starlette | 1,606 | 1 |
| Flask-WTF | 979 | 1 |

All first requests fit the unchanged 12,000-byte cap; source inventories matched
before/after and real model calls remained zero. These requests carry paths,
not the same symbol-map information as v1. Do not present the smaller sizes as
an equal-information compression gain or an end-to-end token/cost reduction.
Workspace listing still hashes the repository. The sentinel stops before file
selection, so **selected symbol maps and repair windows are unmeasured here**.
The full path now normally uses three model requests rather than two.
