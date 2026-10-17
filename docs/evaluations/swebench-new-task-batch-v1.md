# Fixed new-task batch v1

Source: `.keel/swebench/new-task-batch-v1/results.json`.
Plan SHA-256: `8624a3f87fdedbcec24e67c3ed1e68710518a498cb09d40a790aaa7114c3f762`.
Frozen inputs were checked after execution and matched. No failed task was replaced.

| Instance | Reference resolved | Keel officially resolved | Verification rounds | Model calls | Tokens |
| --- | --- | --- | --- | --- | --- |
| astropy__astropy-14539 | yes | no | 4 | 16 | 102387 |
| scikit-learn__scikit-learn-14629 | yes | yes | 2 | 8 | 44032 |
| astropy__astropy-14508 | yes | no | 3 | 18 | 101876 |

Observed resolution: 1/3. Total runtime accounting: 42 model calls, 248295 tokens,
141 tool calls, 3305.439 seconds. Reference preflights and final grading are outside
these runtime totals. This is an exploratory three-task batch, not a representative
benchmark rate or a controlled estimate of recovery benefit. Prior exposure is unverified.

## Observed trajectories

- Astropy 14539: first three rounds failed both target tests while all 46 regression
  tests passed. Fourth verification timed out at 600 seconds. Final official result
  remained unresolved. Earlier observed errors included ambiguous array truth values
  and a non-iterable numpy integer. Root cause of the patch is not established here.
- Scikit-learn 14629: initial target failure, then target and all 26 regression tests
  passed. Recovery also corrected a rejected selection of a protected test file.
- Astropy 14508: target test passed in all three rounds, but one of 174 regression
  tests failed (`test_invalid_float_cards2`). Two ineffective proposals were rejected.
  Local recovery allowance was exhausted; this does not mean every global budget
  was exhausted.

## Generic feedback transport defect

`examples/swebench_verify_workspace.py` emits full test status lists, including passing
IDs, and only the final 6000 characters of observed test output.
`keel/recovery.py::bounded_verification` subsequently retains only the final 4000
characters of stdout. Large reports therefore consume space on successful test IDs,
and traceback details can disappear before the recovery decision. In Astropy 14508,
the observed log tail contained the final failure summary but no detailed traceback.
This establishes information loss, not that it alone caused either failed repair.

Next development priority: structured failing-test summaries and bounded failure
excerpts, with full logs available by evidence reference; distinguish grading timeout
from code-test failure. Verify these generically with long reports and multiple
failure blocks. Preserve this batch and label reruns as development attempts after
any implementation change; do not retrospectively improve its score.
