# SWE-Explore action protocol validation

The 2026-10-14 follow-up reused the Flask snapshot and semantic index from
[the first cascade attempt](swe-flask-first-cascade.md). It changed the model
action protocol, retaining local validation, bounded exploration, and gold labels.

Ollama now receives a JSON schema for the supported actions and visible symbol
IDs. The same schema is included in the prompt for adapters without structured
output support. Invalid actions receive a validation error and visible IDs;
their errors are preserved in routing traces. The final available turn requires
an explicit final selection. Missing or invalid final selections remain incomplete.
Each sweep also writes `events.jsonl` with replies and observations tagged by
mode, line budget, and repetition.

Artifacts: `.keel/swe-protocol-repeat-validation/`. Instance:
`pallets__flask-5014`; commit: `7ee9ceb71e868944a46e1ff00b506772a53a4f1d`;
index reference: `2a0789f121788b3751c52b13b6d19166b643ce7b4ed9866619abe5a82642c578`.
The run used `keel-chat`, the existing `keel-embed` vectors, 100 lines, seed 42,
three repetitions, and per-run limits of 300 seconds, 30,000 tokens, four model
calls and 100 tool calls. A preliminary single-repetition probe used a 60,000
token ceiling; the table below is from the repeated run with the original ceiling.

| Mode | Completed repetitions | Mean model calls | Mean chat tokens | Line recall |
| --- | --- | --- | --- | --- |
| T0 | 3/3 | 0 | 0 | 0 |
| T1 | 3/3 | 0 | 0 | 0 |
| T2 | 3/3 | 1 | 2,069 | 0 |
| Adaptive | 3/3 | 1 | 2,069 | 0 |

All six model responses were valid explicit final selections of the same visible
symbol. No invalid actions occurred; `all_passed=true` indicates execution
completion. The selected context still missed the gold regions, so this validates
protocol adherence on one instance, not improved retrieval quality. Early final
selection remains permitted and does not prove that the model gathered sufficient
evidence. Next work is candidate/context diagnostics and broader task coverage.

This remains a Python-only reference evaluation without official evaluator parity.
Repeated runs share the index and model caches, and concurrent regression checks
make timing comparisons inappropriate. Repetitions do not add independent tasks.
