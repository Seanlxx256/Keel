# Extended-v2: crossed early localization stop, repair still failed

Artifacts: `.keel/swebench/astropy-14508-extended-v2`.
Trial SHA256: `5b72fb08dcbb86f19b73dacaf70f40cda1a8b0caa59831567cc5374ac78ca5d5`.
The trial implementation map matches its frozen plan. The final official report
hash matches grading metadata. This review launched no paid rerun.

## Observed result

- Runtime failed: policy_denied in Implementer, `Proposal targets a file outside current evidence scope`.
- Official unresolved: target 1/1 passed, preservation 171 passed / 3 failed.
- 49 model calls, 324,909 tokens, 71 tools; Agent 1,155.250 seconds.
- Total trial elapsed 1,335.813 seconds (about 22m16s), including additional work
  outside Agent timing. Limits remained 60 calls / 400,000 tokens / 3,600 seconds.
- Four intermediate verifications; no external MCP calls. Four later Critic
  dispatches carried progress context. Ten successful catalog-page flushes were
  recorded, in addition to rejected page responses.

| Intermediate verification | Target failures | Preservation failures |
|---|---:|---:|
| 0 | 0 | 1 |
| 1 | 0 | 3 |
| 2 | 0 | 3 |
| 3 | 0 | 3 |

The final three preservation failures are test_floating_point_value_card,
test_complex_value_card and test_invalid_float_cards2. There is no successful
repair trajectory to optimize from this attempt. The extra allowance permitted
more editing/verification, but the terminal blocker was not a numeric limit.

## Writable contract worked only partially

Protected/out-of-page selections still occurred in ledger facts 17, 18, 20 and
44 despite the schema. Host correction and membership checks prevented those
paths from becoming accepted targets, and the run eventually reached editing.
One outer relocalization recovery was recorded. Do not claim that real-model
schema compliance is solved or that enums eliminate protocol errors. This is
consistent with the documented JSON-object-provider limitation.

## Final target drift is directly visible

In the last localization cycle, fact 113 selected astropy/io/fits/card.py.
The next page response, fact 114, selected utility-module paths and omitted that
previous choice. Final evidence facts 117..119 cover astropy/utils/misc.py,
astropy/utils/decorators.py and astropy/utils/exceptions.py. The validated plan
therefore had only those targets. Proposal fact 121 nonetheless tried to change
astropy/io/fits/card.py and was rejected before application.

These are legal-catalog choices that are inconsistent with the intended change:
valid membership does not establish relevance or preserve investigative focus.
The earlier permission guard should not be relaxed to admit the stale target.
The final rejection is not an environment permission failure or an exhausted
budget. A future change needs a general cross-page/plan consistency contract, not
a hardcoded rule to retain this particular file.

Critic repeatedly requested a source trace/minimal probe, while subsequent edits
continued reshaping float formatting and introduced/retained regressions. No new
runtime probe mechanism or arbitrary model-code execution was added. The current
tools and observations do not establish those proposed causal probes were carried
out. Progress inventory exposed unchanged/regressed outcomes but did not itself
produce an effective correction.

## Cost and retained candidates

Scout used 269,600 tokens (~83%); Critic 26,755; Implementer 28,554. All costs are
descriptive for this seen development attempt, not a component causal estimate.
Five candidate records exist, including the seed. No best-candidate restoration
was applied: terminal policy_denied is outside the existing restore-on-failure
allowlist. Final grading therefore scored the later, worse source, not the seed.
Preserve this outcome; do not silently restore and replace its recorded score.

## Next evidence needed

Use the saved page responses, evidence scopes and failed candidates for offline
diagnosis. Separate cross-page loss of task focus, stale proposal scope and failure
to test formatting hypotheses. Do not repeat another full run or raise the same
budget before a focused correction is reviewed. Do not widen writable permissions,
auto-retain a task-specific target or claim that more reflection alone would solve
it. Successful small controls and a later new real attempt remain necessary.
