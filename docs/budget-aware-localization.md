# Budget-aware localization

The localization catalog now includes `definition_bytes`, aligned with the existing `[line, name]` symbol entries. Sizes count complete original definitions including decorators in UTF-8; they are not token counts or full serialized request sizes. The instruction asks for methods/functions rather than redundant whole-class plus method selections.

After model selection, the host assembles complete selected definitions and preflights the actual proposal request. If it exceeds the configured byte cap, the model gets one refinement request containing the same catalog, previous IDs and explicit capacity error. IDs remain restricted to that catalog. A second oversized result stops without a patch request or writes. Refinement uses the same global budget. Source is never silently shortened. Later evidence collection retains existing source-change checks.

This preflight covers localized source and the proposal schema before optional dependency contracts are added. The final proposal cap still checks all evidence; contract-related overflow remains possible. The refinement catalog itself must also fit the cap. This is bounded selection feedback, not guaranteed successful repair or unrestricted iterative exploration.

Offline replay on Starlette 2526: the size-aware catalog request uses 2,801 bytes; all 55 individually selected definitions fit a 24,000-byte proposal cap. Selecting the TestClient class alone needs 19,738 bytes, while its constructor alone needs 4,310 bytes. The earlier 27,554-byte request combined classes. Thus this task has feasible smaller selections, but the model must still choose correctly. No provider calls were made for this capacity check (`.keel/starlette-localization-capacity-v3.json`).

Preserve the v1 paired results. A new v2 paired cohort uses the new implementation for both feedback arms; do not pool old/new results as identical runs. Both tasks remain known development tasks. Four executions normally require 12–16 model calls, with at most one extra localization refinement call per execution (up to 20 normal calls if all paths are reached), bounded by each original global budget.

```powershell
python examples/run_repair_comparison.py --model-config .keel/model-openai.json --case 2526=.keel/upgradebench-reproduction/a5a65d40fa92407aa5ec9861910988d3 --case flask-wtf-565=.keel/upgradebench-reproduction/60f3db38a28b4bed9585ad4f22f1877d --output .keel/repair-comparisons/development-v2
python examples/run_repair_comparison.py --output .keel/repair-comparisons/development-v2 --execute
```
