# Bounded external-tool recovery validation

Source: `.keel/retrieval-validation/run-v9`. Original run-v7/run-v8 failures
remain archived. The derived plan records worker changes, exact predecessor
compatibility and the updated query-recovery policy. No task or reference label
was replaced, and no embedding index was rebuilt.

## Serena

The Django identifier query overflowed at 864 substring matches. Relative exact
matching also overflowed at 217. `keel.tool_recovery.symbol_queries` then used
Serena's native absolute name-path syntax. The measured execution completed with
seven tool calls under the unchanged eight-call cap and returned three candidates.

The shared recovery trace records the relative-exact action as failed and the
root-exact action as verified. The latter is persisted in the operational experience
store with system, interpreter, tool version, category and query-policy identity.
Verification here means the narrowed query returned a valid response; source range
checks and quality measurement occur separately. A controlled cross-query test
checks retrieval of prior experience and rejects unknown/permission failures.

The result is operational recovery, not a retrieval-quality gain: Django's three
candidates emitted 36 unique lines, with zero overlap with the reference region.
This is a genuine measured zero, unlike an unavailable engine. The deterministic
identifier adapter is not a full autonomous Serena Agent or semantic retriever.

## CocoIndex

An independent server/client named-pipe exchange using the actual CocoIndex
interpreter reproduced WinError 5 at the server and WinError 2 at the client.
This establishes a local transport permission boundary in the current execution
environment. It does not establish that the user's normal terminal is restricted,
nor does it identify a global OS configuration or a model/download defect.

The new transport preflight returns `TransportUnavailable` before source copy,
model loading or daemon startup. In run-v9 it took approximately 3.42 seconds and
executed zero CocoIndex CLI commands. It does not attempt elevation or change
permissions. A normal-terminal retry must run the same probe and keep the original
failure records, rather than mark this attempt successful.

## Reuse and validation

All four Compass baselines were reused. Six previously successful external
measurements were reused after identity and metric checks. Reranker inference
reused 700 cached pairs and scored only the three new Serena candidates.
The batch still has one invalid Xarray input and one unavailable Django CocoIndex
measurement; its status remains incomplete and benchmark_ready remains false.

31 related checks passed: tool recovery, experience, CocoIndex retrieval,
external-result reuse, frozen validation, coverage policy and reranker cache.

To retry only the outstanding runnable measurement from a normal PowerShell:

```powershell
python examples/run_frozen_retrieval_validation.py --plan .keel/retrieval-validation/run-v9/resume-plan/plan.json --resume-from .keel/retrieval-validation/run-v9 --output .keel/retrieval-validation/run-v10 --execute
```

This keeps the explicit valid-Python corpus policy and the existing input failure.
It does not rerun successful work when its inputs/configuration still match.
