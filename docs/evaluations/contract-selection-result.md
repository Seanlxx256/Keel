# Contract selection trial: combined context blocked patch request

`httpx-1588-contract-select-v1` failed before patch generation, with no changed
files: three model calls, 3,375 tokens, ten tools and 21.891 seconds. This is a
capacity failure after evidence selection, not a model-produced incorrect patch.

The model chose six definitions: two default-transport methods and four client
methods. Source evidence alone contains more code than earlier selections.
It also selected four scanned contract IDs. The combined proposal input was
14,973 bytes against a 12,000-byte cap. Prior single-contract checks on different
saved source windows did not guarantee this combination would fit.

## Configuration correction

The fixed 12KB cap originated in constrained local-model experiments, not in a
verified limit of the configured cloud model. Repeatedly adding selection steps
solely to fit that fixed cap was an overly rigid engineering choice. Do not keep
filtering relevant source based on this one outcome or report a blocked request
as repair failure by the model.

The runner now supports preparation-only `--max-context-bytes` (1024..128000).
Default remains 12000. The explicit input cap is frozen in config and reported
in results; execution cannot override it. Host budget/time/permission/verification
checks remain. Bytes are not exact model tokens or a statement of provider
context capacity. Higher allowed input can consume more tokens and is a changed
experimental allowance, even when global call/token/time limits are unchanged.

Exact offline replay of the saved source, baseline observations and selected
contracts reproduces 14,973 bytes: rejected at 12000, accepted at 24000. No files,
definitions, signatures or source lines were removed. Artifact:
`.keel/contract-cap-ablation-v1.json`, zero new model calls. This is capacity
feasibility only; future selections and actual patch correctness are unmeasured.

Runner (5) and localized-proposal (11) tests pass. They check frozen cap values,
type/range validation and the existing source/acceptance/contract boundaries.

## Separate 24KB diagnostic

`.keel/transition-trials/httpx-1588-contract-24k-v1` uses the same model, base,
goal/evidence policy, fixed image, 450-second runtime / 30 model calls / 60 tools /
180,000 tokens / 1024 output limit, with an explicit 24,000-byte per-request cap.
No new architecture or default-mode replacement. It is **not** a same-context-
budget comparison to historical runs and cannot establish runtime speedup.

```powershell
python examples/run_transition_task.py --output .keel/transition-trials/httpx-1588-contract-24k-v1 --execute
```

Preparation only has been performed. Preserve the failed 12KB artifacts. Any
follow-up output remains a development diagnostic, not an independent benchmark.
