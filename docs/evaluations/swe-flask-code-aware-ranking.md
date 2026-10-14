# Optional code-aware ranking experiment

On 2026-10-14, an opt-in ranking experiment reused the snapshot, semantic index,
query, models, 32-line symbol cap and 100-line total budget from
[the context diagnostics](swe-flask-context-diagnostics.md). It used seed 42,
three repetitions, and the same per-run limits: 300 seconds, 30,000 tokens,
four model calls and 100 tool calls.

Artifacts: `.keel/swe-code-aware-validation/`. The baseline artifacts are
`.keel/swe-context-packing-validation/`. Both runs completed all 12 configurations.
Model and OS caches are uncontrolled; timing is not compared.

## Policy

RRF stays the default. The optional `code-aware` policy extracts capitalized and
backtick-delimited terms from the issue, includes simple plural variants, and
retains only terms present in candidate paths or qualified symbol names. It
reweights the fused RRF score using identity coverage and code coverage, with
length normalization to avoid rewarding large containing scopes merely for
including more code. It preserves the candidate set and requires no additional
model or embedding calls. It uses no labels, issue IDs or repository-specific rules.
The weights and plural handling are heuristics and need broader validation.

## Results

| Mode | RRF file hit | Code-aware file hit | RRF line recall | Code-aware line recall |
| --- | --- | --- | --- | --- |
| T0 | 0 | 0 | 0 | 0 |
| T1 | 0.5 | 1.0 | 0 | 0.03195 |
| T2 | 0 | 0.5 | 0 | 0 |
| Adaptive | 0 | 0.5 | 0 | 0 |

All three repetitions agree on these metrics. T1 emitted 100 unique lines, with
line precision 0.20: 20 gold lines out of 626 were recovered. The relevant
`test_dotted_name_not_allowed` candidate moved from rank 12 to rank 3;
`Blueprint.register_blueprint` moved from rank 22 to rank 2.
T2 and adaptive selected `test_unique_blueprint_names`, emitting 15 lines with
no gold-region overlap. Better candidate ranking therefore does not yet solve
model evidence selection.

These are exploratory results on the same single development instance used to
investigate failures. They establish neither benchmark-wide improvement nor
generalization. Gold annotations include a broad file-sized region, so line
overlap does not prove precise edit localization. Next work should broaden
development coverage and evaluate held-out repositories before changing defaults.
Official evaluator parity remains unverified.

To request this policy in the public preparation runner:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\examples\run_swe_public.ps1 -Ranking code-aware -Repeats 3
```

For existing snapshots, pass `--routing examples/code_aware_routing.json` to
`python -m compass benchmark swe-sweep` with the usual dataset and snapshot flags.
