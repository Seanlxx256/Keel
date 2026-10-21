# Failure-location diagnostic pair v1

Plan SHA256: 5eb9ccb68e8d27b92ae42519b11523bc7b5d94226720ef106e909fab81038b34.
Both result receipts and aggregate report verified. Same current prompt/schema and
source; user payload differs only by failure_locations and its omission count.
One known development context, fixed summary-first order, one call each.

| Arm | Tokens | Seconds | Observation |
|---|---:|---:|---|
| Exception tail only | 5,813 | 11.093 | Places failure in later warn-mode rewrite without supporting caller evidence. |
| Caller frame added | 6,088 | 9.969 | Correctly names initial hdu.writeto, but still reasons about later corruption/rewrite. |

Total 11,901 tokens; caller arm costs 275 additional tokens. No source edits,
runtime probes or repair tests occurred. Both outputs structurally valid, no
soft-length warnings, both route replan.

The caller arm's LOCATION is more accurate, but its later-corruption explanation
does not consistently follow the observed execution order. It proposes checking
whether failure happens after the deliberate byte edit even though the supplied
frame shows failure in the earlier write. The proposed support/refutation wording
is not evidence that either outcome occurred. This is partial evidence consumption,
not a closed diagnostic loop or a verified root cause.

Next priority: evidence-to-hypothesis consistency and an actual narrowly scoped,
budgeted execution check if authorized, using existing verification isolation.
Do not keep rewarding a changed LOCATION label as successful reflection, and do
not infer effectiveness of more prompt edits without execution evidence. Preserve
the generic caller extraction because it delivers relevant evidence, without
claiming this single pair improves repair rate or cost.

Raw results: .keel/repair-review/failure-location-pair-v1/results/report.json.
