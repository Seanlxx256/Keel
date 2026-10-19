# Frozen new-task retrieval validation

For interrupted `run-v2`, follow the verified continuation command in
[resume instructions](retrieval-validation-resume-v1.md). The original execution
command does not reuse completed work or migrate implementation receipts.

Frozen plan: `.keel/retrieval-validation/plan-v1/plan.json` (digest alongside).
Implementation: `examples/run_frozen_retrieval_validation.py`.

Five tasks, one per repository, selected before snapshot preparation and scoring:

| Task | Repository |
|---|---|
| psf__requests-2317 | psf/requests |
| pytest-dev__pytest-7324 | pytest-dev/pytest |
| pydata__xarray-4687 | pydata/xarray |
| astropy__astropy-8707 | astropy/astropy |
| django__django-14725 | django/django |

These are five repositories, not five previously unused repositories. New means
not present in the scanned local experiment records, not proven training-unseen.
The plan records scanned exposure receipts and excludes 17 prior task IDs,
including plans and failures. It does not assume absent records prove no exposure.

Data are already cached pinned SWE-Explore and SWE-bench Verified exports.
Selection uses the existing metadata eligibility/small-repository preference,
seed 20261018 and no observed retrieval quality. The plan records all data,
exclusion, implementation and per-task dataset hashes. Failed tasks are retained;
there is no reserve promotion. The earlier three tuning tasks are excluded.

## Frozen arms

For each engine (Compass code-aware T1, Serena symbol adapter, CocoIndex native
semantic retrieval), compare original order, MiniLM reranker order, and equal
weight RRF with constant 60. The same 100-line budget and 32-line prefix cap
remain. No candidate fusion or query-aware snippet policy is added.

The reranker revision is pinned to the already downloaded cache revision
`233902d25c440f23af6f7d6e94d2946bac0bee0a`, with CPU/batch-eight/512-token
settings unchanged. The existing reranker cache is reused through the new
`--model-cache` option. Embedding/package versions are not all independently
pinned, so this is a fixed-policy validation, not a fully hermetic experiment.
Current environment specifications and engine versions are retained in outputs.

No chat-model API key is required. Compass uses the existing local Ollama
`keel-embed` service; external engines reuse their isolated interpreters. First
use of a new output location can require embedding-model downloads. Larger
repositories also take longer to index. This is retrieval evaluation, not Docker
repair testing or official SWE-bench task grading.

## Execution

Use the existing plan without resampling:

```powershell
python examples/run_frozen_retrieval_validation.py --plan .keel/retrieval-validation/plan-v1/plan.json --output .keel/retrieval-validation/run-v2 --execute
```

Run from the project root in the usual configured terminal, with Ollama running.
The script prepares the fixed snapshots, builds semantic Compass indexes, runs
T1 only, calls external retrievers, scores cached candidates with the fixed
reranker and replays fixed fusion. It preserves all intermediate artifacts.
Plan/implementation/task hashes are verified before execution. Do not edit a
plan and its digest to bypass an implementation mismatch; document a new plan
revision before running changed code.

`validation.json` reports every planned task, stage failures, engine exclusions,
and paired summaries. `completed` requires all five baseline tasks and external
engines to finish; missing tasks are neither zero quality nor silently replaced.
Summary rows state their own task counts; do not compare averages from different
subsets as matched engine results. Intermediate `baseline_ready` is a stage,
not a claim that a repair succeeded.

## Current evidence

The actual execution `.keel/retrieval-validation/run-v1/validation.json` retained
all five tasks as infrastructure failures at snapshot fetch: GitHub connections
were refused through the execution environment's configured proxy. No baseline
retrieval or reranker calls were reached. There are no new-task quality results
yet. The same plan can continue from another execution directory without
changing selected tasks.

Validation: 16 related tests passed. New checks cover exclusion of failed/planned
tasks, rejection of modified plans, and retention of failed tasks without
substitution or generated scores. Full successful five-task orchestration is
still unverified; downstream components have prior real development runs.
