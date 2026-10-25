# Sphinx 9602: probe-informed continuation accepted

Reviewed 2026-10-25. This is an exposed development continuation, not a fresh-base
or first-attempt result. Previous failed attempts and their costs remain valid.

## Verified outcome

The Agent-produced patch passed both its isolated official-harness verification
and a separate fresh final official grade. Final report: `resolved=true`, patch
applied successfully, one FAIL_TO_PASS and 45 PASS_TO_PASS tests passed, none
failed. Raw pytest output reports 46 passed and 191 warnings. This covers the
task's acceptance suite, not the entire Sphinx repository.

Final-grade artifacts:

- `.keel/swebench/sphinx-9602-probe-informed-final-grade-v1/grading.json`
- Run `keel-e3a3c369a67443ea9dabcdd2755288b9`
- Raw report SHA256 `f1eca2ce286f1b2674d61c63a3cc68aee3f6cd17661629dacdb9579baf437ce7`

The review verified the raw report hash and all frozen final-grade inputs.
The grader used the unchanged prediction exported by
`.keel/swebench/sphinx-9602-probe-informed-v4`; its prediction and runtime-result
hashes still match the export receipt. Retained instance images were reused,
while the final test container and test outcome were fresh.

## Successful continuation

The successful Agent attempt used GPT-5.4, four model calls, 27,275 tokens,
eight tools, and 160.859 runtime seconds. It proposed one new candidate and
passed its first verification. The audit records only
`sphinx/domains/python.py` changed, no unexpected files and no findings;
`metadata_checked=false`, so this is not an assertion of exhaustive anti-cheating
coverage. These costs exclude earlier failures, diagnostic experiments, seed
grading, and final grading.

The seed was the last failed archived candidate, matched to the v5 real parser
probe. The raw probe and current source allowed the model to reason about why
the prior condition did not take effect. No developer-written business patch
was inserted. Source and diagnostic hashes were checked before continuation.

Earlier progress required developer changes to candidate import isolation,
fixture preparation, action protocol consistency, seed byte preservation and
launcher interfaces. Developer-provided fixture initialization is disclosed.
The larger process therefore remains human-guided system development; this
single successful continuation does not establish autonomous harness evolution
or a causal effect of any one change.

## Final-grade recovery

The original v4 trial remains `status=error`, `runtime_status=passed`, with no
final official score. Its final grader failed before launch because a PathLike
interpreter argument entered a JSON command receipt. The shared grading API now
normalizes that argument to a string; 40 related bridge/task checks passed.

The recovery graded the same exported patch in a new output directory with
zero model calls. It did not repeat source repair or overwrite the original
failure. This document reconciles the passed runtime, failed first final launch,
and successful independent final grade without relabeling old artifacts.

## Interpretation and next measurement

This is a completed cross-repository development checkpoint: a saved-source
diagnostic observation was followed by a model-generated correction and fresh
official acceptance. `benchmark_ready=false` remains appropriate because the
task was repeatedly exposed and the continuation used developer-assisted
diagnostic preparation.

Freeze this successful source/runtime/evidence chain as a regression example.
Next measure a generic mechanism on independent failure cases with the same
parent configuration, fixed budgets, repeated comparisons, and all scheduled
outcomes retained. Neither this result nor the small earlier memory comparison
proves improved first-attempt success, stable cost reduction, generalization,
or recursive self-improvement.
