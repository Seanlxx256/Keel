# Transition trial offline diagnostics

The first four model-executed HTTPX preparations were analyzed without new model
calls. Original artifacts were not modified. This is a development failure
analysis, not four independent tasks or a comparison of model success rates.

| Trial suffix | Calls | Runtime seconds | Terminal stage | Edit attempts |
| --- | ---: | ---: | --- | ---: |
| path-fix | 23 | 169.391 | Implementer turn budget | 0 |
| pagination | 12 | 79.296 | Scout turn budget | 0 |
| envelope-fix | 6 | 43.625 | Planner item count | 0 |
| planner-feedback | 19 | 123.688 | Implementer turn budget | 0 |

All four have disposition `no_edit_attempt`. A failure before editing does not
establish inability to write the migration patch, nor does it establish that
more turns would help. Different runtime implementations and sampled model
outputs prevent interpreting the timing differences as a controlled speedup.

`keel.trial_diagnostics` reads results, JSONL events and the SQLite ledger in
read-only mode. It joins tool outcomes by call ID, accounts for model calls,
protocol errors, envelope normalization and archived turns per role, and counts
exact duplicate read/search/list requests separately from cache hits. It records
hashes of the source files and omits raw source/model text from its output.
Tool receipts are observations, not independent patch-correctness proof.

Reproduce (output must not exist):

```powershell
python examples/analyze_agent_trial.py --trial .keel/transition-trials/httpx-1588-path-fix --trial .keel/transition-trials/httpx-1588-pagination --trial .keel/transition-trials/httpx-1588-envelope-fix --trial .keel/transition-trials/httpx-1588-planner-feedback --output .keel/transition-trial-diagnostics-v1.json
```

This report has already been generated locally. It makes zero model requests.
Malformed or missing artifacts fail analysis instead of being silently excluded.

## Offline regression coverage

Existing Agent tests cover evidence-gated Scout envelope handling, planner
item-count recovery within the same budget, oversized-read continuation through
an exact edit and real local verifier, early completion refusal, scope denial,
model/tool limits and model claims that cannot bypass verification. Gateway tests
cover pagination bounds, exact source continuity, budget charges and permission
checks. Audit/mutation suites independently cover rejected verification bypasses.
These scripted tests prove host behavior, not live-model decision quality.

The next paid experiment should be planned as one bounded development rerun
after implementation freeze. Do not tune prompts after each outcome or relabel
this task as held-out. A simple-versus-multirole comparison still requires a
shared task interface, equivalent source/tool access and recorded total costs;
operator-localized proposal runs are not a fair autonomous-retrieval baseline.

## Regression execution

On 2026-10-16 the dependency-complete Python environment ran
`python -m unittest discover -s tests -q`: 336 tests in 123.327 seconds,
334 passed, one failure and one error. Both nonpassing checks involved official
MCP SDK subprocess startup with `PermissionError` / Windows error 5:
`test_real_compass_stdio_schema_errors_and_shutdown` and
`test_real_official_sdk_interoperability`. This is consistent with the restricted
tool environment, but does not count as successful interoperability validation.
No tests were changed or skipped to conceal those failures. Recheck those two
suites from the user's ordinary terminal before declaring the full suite green.
The new offline diagnostics test passed, including read-only ledger preservation
and classification of rejected edits separately from completed tool actions.
