# Repair evidence acquisition and constrained refinement

Two generic corrections follow the development-v2 failures.

1. After initial localization overflows, the single refinement catalog explicitly excludes classes containing direct methods. Remaining function/method definitions retain exact source and line IDs. Selecting an excluded class is rejected before patching. This constraint applies only after overflow; initial class selections remain possible. It avoids asking the model to repeat the same oversized class choice, without choosing the known correct method for it. Multiple methods can still jointly exceed the cap, in which case the run stops.
2. When traceback-focused repair evidence omits original declared files, a model evidence-selection step exposes current symbol catalogs for all original declared files plus bounded observed errors. The model selects exact definition IDs, the host reads those complete current definitions and checks source stability, and only those evidenced files become editable for that proposal. This permits reacquiring a previously omitted file without allowing unobserved edits or expanding the original permission scope. Selected source may still overflow the proposal cap; there is no guarantee of success.

The additional selection uses the existing global model/token/time budget. It is logged as `repair-evidence-selection`; original traces, acceptance and audits remain in effect. No task-specific snippets or gold changes are injected. This is a bounded extension to the existing proposal workflow, not a replacement of the six-role design.

Tests include a cross-file failed-verification fixture that omits one file, explicitly reacquires its evidence, patches it and passes mocked acceptance; this is an interface integration test, not real Docker repair evidence. Other tests reject stale source, unknown/out-of-scope locations and exhausted shared budgets. Original task success still requires a live trial.

A fresh development-v3 cohort is prepared for the same two tasks. Preserve v1/v2, do not pool implementations, and do not claim held-out coverage. Depending on refinements and feedback, normal execution can use approximately 12–24 model calls across four arms; global configured budgets remain authoritative.

```powershell
python examples/run_repair_comparison.py --output .keel/repair-comparisons/development-v3 --execute
```
