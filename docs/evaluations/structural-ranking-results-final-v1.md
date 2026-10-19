# Structural validation v1: continuation complete, three pairs accepted

The bounded continuation supervisor finished after two additional rounds with
checkpoint/completion progress. It stopped because no retryable index-budget
failures remained. Elapsed supervisor time was about 2,383 seconds, including
waiting for the in-flight round. No frozen ranker settings or tasks changed.

Source run: `.keel/structural-validation/run-v1/run.json`.
Final audit: `.keel/structural-validation/run-v1/acceptance-final.json`.
Continuation: `.keel/structural-validation/continuation-v1/continuation.json`.
The earlier two-task partial acceptance remains preserved.

## Three complete paired tasks

| Arm | Mean line recall | Mean line precision | Mean file hit rate |
|---|---:|---:|---:|
| Original Compass | 6.160% | 58.33% | 70.00% |
| Same-pool structural ranking | 6.285% | 60.33% | 70.00% |
| Native Aider ranked-tag component | 1.056% | 8.67% | 16.67% |

Requests 6028 improves from 79% to 85% precision. Pytest 7571 stays at 68%.
Django 16116 stays at 28%. Structural ranking has one win and two ties on
completed tasks; no default promotion or significance claim follows. Compared
with original Compass, mean precision increases 2 percentage points and recall
about 0.125 percentage points. These are component metrics, not repair rates.

The final audit checked the original plan and implementation hashes before the
subsequent preflight implementation change, all task receipt hashes, successful
artifact hashes and source/index freshness. It reproduced all metrics for all
three arms on the same three tasks, and checked structural candidate membership.
There were no additional model calls during acceptance. Completed Requests and
Pytest results were reused rather than rerun.

## Two retained scope exclusions

Xarray 3993 includes `doc/computation.rst` and `doc/whats-new.rst` in its reference
files. Astropy 12907 includes `pyproject.toml`. All indexes finished, but those
references exceed this experiment's declared Python corpus. They remain explicit
exclusions; no reference lines were removed and no reserve tasks were promoted.
Five-task completion is not claimed. Completion-based selection can bias these
three-task averages. The source report therefore correctly remains incomplete.

## Prevention for future runs

`compass.evaluation_scope.reference_scope` compares reference files against the
indexer's actual source inventory and file-size limit before embedding. It is an
evaluation-layer eligibility gate, not retriever context. The reference paths are
not supplied to any adapter. A retrospective check on all five frozen tasks
identifies exactly the two observed scope exclusions, without indexing/inference:
`.keel/structural-validation/scope-preflight-audit-v1.json`.

Future structural plans pin this preflight policy and helper implementation. The
runner records `out_of_scope` before invoking embedding or native tools. Three
new checks cover docs/config rejection, ignored/oversized files and a runner-level
assertion that neither indexing nor native tools starts for out-of-scope tasks.
Ten related structural/preflight/continuation checks passed. Passing the early
scope gate does not prove parse completeness; final coverage checks stay active.

The completed v1 experiment is closed. Its old runner bytes were archived at
`.keel/structural-validation/run-v1/frozen-runner.py` and verified against the
original plan hash before adding the new gate. Current runner implementation has
changed, so do not resume the old frozen plan with current code. A future run
requires a newly frozen plan; old results and exclusions are not reclassified.

No documentation/configuration retrieval has been implemented by this gate.
Expanding the corpus would require a separate declared experiment, comparable
native-engine language support and independently validated range/chunk handling.
