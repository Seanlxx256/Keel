# W8 controlled local memoization measurement

The runtime now accepts top-level boolean `memoization` (default true).
False bypasses local file-read, file-list and literal-search cache reads/writes,
while retaining permissions, budget charges, snapshot guards and source results.
It neither bypasses audits nor changes Compass/MCP/model behavior.

`result.memory` includes per-tool requests/cache_hits/computations, plus full
workspace snapshot call/byte counts. Computations count attempted decode/list/scan
invocations, not physical disk reads or saved model requests. File-read hits still
read source bytes; list/search hits still perform pre/post fingerprint scans.

## Protocol

`python -m keel.memory_benchmark` generates a fixed synthetic Python repository.
Each trial runs both modes in alternating order with a seeded initial mode,
a fresh ledger per mode, the same repository path and identical initial bytes.
Two phases each issue repeated read/list/absent-text search calls. A real scoped
replacement changes VERSION between phases; its internal read is also counted.
The absent-text query forces a full scan on a cache miss. Semantic outputs strip
only cache-hit/repetition fields before hashing and comparison. Final source
bytes must also match the expected edit. Model calls and embedding calls are zero.

Timing excludes fixture/ledger construction and includes Workspace operations,
source hashes, cache I/O, trace writes and the edit. OS caching remains uncontrolled.
This direct-Workspace experiment does not measure gateway serialization, LLM
context size, duplicate model requests, or real-task resolve rate. It deliberately
retains fingerprint guards in both modes rather than confounding cache reuse
with removal of correctness checks.

## Initial result (2026-10-15)

Artifacts: `.keel/memory-bench/a64fc43139104c6ab3f38c7ae5969b47`.
64 files, 128 assignment lines plus a VERSION line per file, 5 repeats per phase,
2 phases and 3 paired trials, seed 42. All outputs and final bytes matched.

| Metric | Cache off | Cache on |
| --- | ---: | ---: |
| Observation requests per trial | 31 | 31 |
| Computations per trial | 31 | 6 |
| Cache hits per trial | 0 | 25 |
| Snapshot bytes per trial | 5,144,680 | 5,144,680 |
| Median seconds | 0.749332 | 0.799197 |

The median-time ratio on/off is 1.0665: this workload was about 6.7% slower with
cache enabled. Fewer computations do not establish lower latency. Persistent
cache and hashing costs remain material for cheap local operations. No token
savings or reduced duplicate-call rate is claimed. This is a negative timing
result on one synthetic workload, not a universal conclusion about caching.

## Existing live context-handoff evidence

The user completed `.keel/agent-smoke/30d95ed716e645939b46c234820dcdff`
with context handoff, CPU inference, a 4096 context window and Docker verification:
all six smoke checks passed, 8 model calls, 168.25 seconds, 2 handed-off facts,
2 cache hits and 20 exported spans. This differs from earlier no-handoff settings;
it is not a paired experiment and cannot establish a handoff speedup.

W8 functionality is validated; broader overhead measurements and model-cost
ablations remain distinct experiments before any efficiency claim.


## Larger fixture and validation

A separate 256-file fixture with 512 assignment lines per file used the same
5 repeats/phase, 2 phases and 3 paired trials. Artifacts:
`.keel/memory-bench/ddd1a6e7f9d94f85af8bbd4e8031cc1a`.
All semantic outputs/final source bytes matched. Requests remained 31, computations
31 -> 6, cache hits 0 -> 25, and fingerprint bytes were 87,931,480 in both modes.
Median seconds were 3.256131 off and 2.954965 on, approximately 9.2% lower.
Each experiment is internally paired; different fixtures and uncontrolled OS
caches do not establish a causal scaling law or statistical significance.

Both positive and negative timing results are retained in
[the portable report archive](keel-memory-measurement.json), with source hashes.
The initial reports preceded addition of environment/implementation-hash fields;
new benchmark runs also record those fields and emit per-trial console progress.

Full regression before the final runtime-switch test addition: 215 tests,
210 passed, 5 optional-dependency skips, no failures. Final memory suite:
9 tests passed, including disabled-cache lookup bypass, unchanged budget charges,
paired semantic equality, no-overwrite output and independent runtime acceptance
with memoization disabled. Whitespace checks passed.

This closes the first W8 functional and component-measurement milestone. Live
model-token savings and larger real-task ablations remain unproven; framework
adapter work can proceed without representing those as achieved benefits.
