# First Keel trial on sympy-16450: failed repair, failed replanning

The exploratory trial produced a source patch in `sympy/simplify/simplify.py` and ran one official verification. The target `test_posify` failed; the saved observed output reports 40 passed, one failed and two expected failures. A separate final official grading also returned unresolved. This is an actual repair failure, unlike prior interface/environment preflights. No test or acceptance change is used to reinterpret it as a pass.

Runtime totals: eight model calls, 59283 tokens, 25 tools and 370.187 runtime seconds. Final official grading is additional to runtime accounting. The six-action recovery allowance was not consumed in full: four actions were recorded; the repeated-failure guard stopped the third repeated unchanged localization failure. Global model/token/time limits were not exhausted.

Ledger inspection shows the initial and subsequent invalid file selections included `sympy/simplify/tests/test_simplify.py`, a protected test path outside the supplied writable source catalog. The Critic selected replan after the failed verification, but Scout repeated this selection despite correction attempts. The previous generic error omitted the offending path and conflated missing files with protected paths.

The generic localization contract now explicitly distinguishes test paths in observed failures from writable source targets and returns the exact out-of-catalog selections in the validation error. A regression test exercises a rejected test target followed by a valid source selection, verifies feedback includes the path and constraint, and confirms tests remain unchanged. The adapter does not provide a task-specific solution or silently discard invalid model selections. Whether this improves subsequent model behavior remains unmeasured.

This task is now a development case; do not treat a later rerun after protocol changes as independent evidence. The first failure and its costs remain part of the record.
