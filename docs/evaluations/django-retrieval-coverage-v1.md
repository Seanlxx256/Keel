# Django retrieval corpus coverage diagnosis

The run-v6 vector build finished and published generation
`84ce2f8e42724bd7916c67580a32b39d`: 36,510 symbols, reusing 35,648 vectors and
embedding 862 more. The later T1 measurement was correctly excluded by the
strict completeness gate, not by a missing vector or stale source.

The index contains 2,733 Python files and one diagnostic:
`tests/test_runner_apps/tagged/tests_syntax_error.py`, line 11. Its literal
`1syntax_error` is deliberately invalid. Upstream
`tests/test_runner/test_discover_runner.py::test_tag_fail_to_load` imports it
inside `assertRaises(SyntaxError)` and checks the failed test-discovery identity.
The source file SHA-256 is
`4c2711a05b298e58d205a524b13175da984cc4bf94d7056d50836fb4eb6aba52`.

The correction introduces a general, explicit valid-Python corpus policy rather
than a Django-specific path exception. Both AST and tree-sitter must reject the
indexed bytes. Other diagnostics remain blockers, and missing reference source
also blocks a task measurement. The index remains marked incomplete under the
original strict policy. No source, reference labels, output budget or ranking
policy is changed; original run-v6 failure is retained.

The new policy must be recorded in a derived plan. Existing successful strict
baselines can be reused because they have no excluded files; their original
metrics are independently reproduced. This is an amended-scope exploratory
experiment, not proof of strict full-corpus completeness or agent repair success.

## Executed validation

Run `.keel/retrieval-validation/run-v7` finished under the explicitly amended
`valid-python` policy. Its parent run-v6 remains unchanged. The worker reused the
published index without embedding calls. Three completed strict baselines and
their six external measurements were reused after identity/metric checks.

Django T1 now passes the amended eligibility gate: 100 emitted unique lines,
line precision 0.64, line recall 0.032955715756951595 and core-file hit rate 0.5.
The original `complete=false` and exact invalid-source diagnostic remain visible
in the sweep. All reference files are indexed; the invalid fixture is not one.

The batch retains four baseline-ready tasks out of five. Xarray's original
invalid reference interval is still an input failure, without label repair or
task replacement. Django's external engines remain explicit failures: Serena's
broad identifier query exceeded its 100-match cap; CocoIndex reported daemon
startup timeout. The latter log also contains a failed telemetry request, which
does not establish the timeout's root cause. Neither failure is counted as zero
retrieval quality. Thus the batch remains incomplete and is not an all-engine
comparison on four paired tasks.

Validation: 36 checks passed across index coverage, sweeps, frozen validation and
Compass. Coverage checks include two unrelated invalid-source paths, unchanged
strict-mode behavior, source hash invalidation, valid-source extraction failure,
file-size blockers and refusal to admit missing reference source.
