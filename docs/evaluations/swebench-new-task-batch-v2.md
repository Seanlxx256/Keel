# Fixed five-task batch v2

Source: `.keel/swebench/new-task-batch-v2/results.json`. Frozen inputs were
rechecked after execution and matched. Tasks were not replaced after failures.

| Task | Reference | Agent | Official repair result |
| --- | --- | --- | --- |
| pylint-dev__pylint-7277 | grading error | not run | unavailable |
| pydata__xarray-4966 | passed | ran | resolved |
| pytest-dev__pytest-5809 | grading error | not run | unavailable |
| matplotlib__matplotlib-20859 | passed | preparation error | unavailable |
| sphinx-doc__sphinx-11510 | passed | ran | unresolved |

Five planned, three reference preflights passed, two agents executed, one officially
resolved. This is one confirmed success out of five planned tasks, and one of two
executed repairs. Neither denominator supports a general success-rate claim.

Observed blockers:

- Pylint: instance image build failed during editable installation because the build
  backend lacks `build_editable`. This is not an agent repair failure.
- Pytest: official harness failed writing test output with Windows GBK encoding
  (`UnicodeEncodeError` on U+263A). No reference verdict was produced.
- Matplotlib: reference passed, but Windows denied renaming `repo.partial` to `repo`.
  Agent inference did not start. File-lock/permission cause remains unverified.
- Sphinx: actual repair failure. Three verification rounds; initial two failed both
  target tests, third introduced `AttributeError: can't set attribute` when assigning
  the environment docname. Recovery diagnoses were recorded; the subsequent Scout
  exhausted the global 80-tool-call limit. Final official grading was unresolved.
- Xarray: first verification passed and independent official grading resolved;
  3 model calls, 9552 tokens, 13 tool calls, 273.578 runtime seconds; no recovery.

Executed-agent totals: 17 model calls, 81682 tokens, 93 tool calls, 1237.781 runtime
seconds. Reference preflights and independent final grading are outside these totals.
Compass retrieval was not part of this batch. No causal recovery improvement is
established: the success did not exercise recovery, while Sphinx recovery failed.

Next work should separate generic infrastructure fixes from Sphinx recovery analysis.
Preserve this baseline and label retries as follow-up development attempts.
