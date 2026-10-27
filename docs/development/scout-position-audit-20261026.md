# Scout score position audit

This is a zero-model descriptive audit of six completed panels from
`.keel/finetuning/scout-score-training-v1/results`. Output and input SHA256
bindings: `.keel/finetuning/scout-position-audit-v1/report.json`.

Pairs require identical training receipt, dataset, checkpoint, selection policy,
sample coverage, source locations and teacher membership. Candidates are paired
by sample and source location, never candidate ID or list index. Position means
normalized catalog rank, not absolute token offset. Number spelling can change
token lengths even when rank is unchanged.

Each comparison contains 7 exposed queries and 567 candidate instances.

| Compared with original | Mean absolute probability change | Threshold crossings | Rank/score delta correlation |
|---|---:|---:|---:|
| Training ID shuffle | 0.0350 | 17 | undefined: no rank movement |
| Training catalog shuffle 1 | 0.0784 | 40 | -0.0152 |
| Training catalog shuffle 2 | 0.0919 | 47 | -0.1379 |
| Reversed IDs | 0.0422 | 25 | undefined: no rank movement |
| Evaluation catalog shuffle | 0.1251 | 63 | -0.2410 |

Threshold crossings use the existing 0.5 threshold; they are not final set errors
because capped selection and teacher membership also matter. No threshold was fit.
Pooled correlations are descriptive, mix queries, and cannot identify causality
or rule out nonlinear position/context effects. These are not independent tasks.

Observed numbering sensitivity exists without rank movement. Catalog shuffles
also change prefix context and token positions, so their larger drift cannot be
attributed solely to causal visibility. Candidate-end states still structurally
cannot see later candidates, but this is not established as the sole root cause.

Next controlled design: separate ID-text removal from full-catalog visibility.
First validate a label-free candidate representation and input alignment; then
compare trained variants under frozen exposure, selection policy and evaluation
presentations. Changing representations only at inference on the old head would
introduce distribution shift and would not isolate training-time visibility.
Do not reuse the observed evaluation outputs to tune a new threshold.

Reusable implementation: `keel.scout_position_audit.audit_pair`. Three regression
tests passed: location pairing despite reordering, undefined constant correlation,
and rejection of incomplete/identity/label/coverage drift. No GPU forward,
optimizer update, hosted call or production promotion occurred.
