# Frozen diagnostic model contrast, 2026-10-23

One exposed, developer-assisted Astropy case; no patch or acceptance requested.
Inputs/prompt/image/policies identical; only model config name differs.
Per arm: 3 calls, 120 seconds, 60k tokens, 8 tools, 32k request bytes,
2048 output tokens per call; provider defaults retained. One repetition each.

| Observation | GPT-5.4 mini | GPT-5.4 |
|---|---|---|
| Calls / reported tokens | 2 / 15,300 | 2 / 14,715 |
| Seconds | 25.625 | 31.031 |
| Executed probes | 2 | 2 |
| Child outcomes | Both import failures | Both completed |
| Candidate module execution markers | Empty | Expected card/header hashes |
| Stop | Local request capacity | Local request capacity |
| Final diagnosis / repair acceptance | Neither | Neither |

Evidence: `.keel/repair-review/model-contrast-v2/{mini,full}/results/report.json`,
`probe/trace.jsonl` and `probe/ledger.sqlite` facts 1 through 4.

Mini manually loaded partially initialized qualified module, then attempted a
standalone module name losing relative-import context. Its correction did not
recover execution. Full used normal qualified imports and candidate loader worked.
Full's first probe observed `_format_float(1e21)` yielding `1e+21.0`, and parsed
raw cards retaining their strings. Second tested a long exponent raw card: verify
returned no errors, complete rendered card preserved the original value string.
The script's `rendered[10:30]` comparison crops the field itself; its False outputs
do not prove the library truncated or rewrote the complete card. Neither probe
executed the exact failing initial HDU write, nor established regression causality.

Both third model requests were blocked by the host's 32,000-byte input limit,
not provider context exhaustion, total token depletion or wall-clock exhaustion.
First request 26,201 bytes for both; second 31,513 mini / 30,428 full. Full had no
opportunity to interpret its second observation in another model call.

Conclusion: full achieved executable candidate probes where mini did not in this
single run. No evidence yet of a correct complete diagnosis or higher repair rate.
Common host context accumulation prevents observing completion for either arm.
Next engineering work should preserve raw evidence while compacting request views,
then explicitly version and rerun both conditions under the same revised policy.
Do not silently increase only one arm's cap or discard these costs/results.
