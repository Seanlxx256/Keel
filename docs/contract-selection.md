# Bounded model selection of installed dependency contracts

Optional configuration: localized-proposal + localization_dependencies +
`select_dependency_contracts: true`. Defaults remain unchanged. This is an
evidence-selection stage, not another Planner or automatic repair retry.

After fresh static scanning in the fixed image, public/protocol signature entries
are assigned exact dependency/index IDs. One bounded model request receives the
task (including baseline observations when enabled) and the signature catalog.
It returns 1..8 existing IDs only. The host copies the original signatures and
inventory hashes; it does not accept model-written API descriptions. Unknown or
duplicate IDs and invalid shapes fail. Selected signature indices, available
count and subset limitations accompany patch evidence. Full scan artifacts and
the raw selection remain archived. Omitted signatures can still be relevant.

All four stages (file choice, definition choice, contract choice, patch) consume
the same global model/token/time budget. Each request enforces its byte cap.
More than one selected signature can still exceed the combined patch cap; that
failure remains visible. No source is silently truncated to make contracts fit.
No retry budget is added, and signatures are not proof of runtime behavior.

## Offline validation

The observed development source windows and scanned 24-entry catalog produce a
4,949-byte selection request. Each of 24 hypothetical one-contract patch requests
fits 12KB; maximum 11,227 bytes. Artifact
`.keel/contract-selection-preflight-v1/summary.json`. The non-network sentinel
stops before provider invocation. This is capacity only, not a model choice or
guarantee for multiple selections. It does not establish repair success.

Localization integration (11), runner (5), dependency evidence (7) and proposal
(13) suites pass: 36 tests. They cover original signature provenance, selection
IDs, shared budgets, rejection before edits, untrusted-data labeling, version
freezing and no calls during preparation.

## One development execution

Preparation-only CLI flags `--dependency-module module[:distribution]` derive
the exact version from the package's acceptance pins. The module/distribution
mapping is explicit, not inferred from gold data. `--select-contracts` freezes
the additional model stage. Both flags are rejected at execution, which uses
the prepared configuration. Runtime infers symbols from freshly localized source
and rescans the fixed image; the earlier candidate/probe is not model input.

Prepared directory: `.keel/transition-trials/httpx-1588-contract-select-v1`.

```powershell
python examples/run_transition_task.py --package .keel/task-packages/httpx-1588-v1 --model-config .keel/model-openai.json --strategy localized-proposal --baseline-feedback --require-change --dependency-module httpcore --select-contracts --output .keel/transition-trials/httpx-1588-contract-select-v1
python examples/run_transition_task.py --output .keel/transition-trials/httpx-1588-contract-select-v1 --execute
```

Preparation has been completed without provider/Docker calls. No new live model
result is claimed. This is a repeatedly observed development case, not an
independent benchmark or causal improvement over earlier runs. Preserve any
failed selection, patch or acceptance and analyze before another paid action.
