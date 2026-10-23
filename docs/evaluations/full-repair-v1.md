# GPT-5.4 repair continuation v1, 2026-10-23

Evidence: `.keel/swebench/astropy-full-repair-v1/trial.json`,
`run/ledger.sqlite`, `run/trace.jsonl`, `final-grade/grading.json`.

Outcome: unresolved, no new repair candidate; selected saved seed, official
grading failed without infrastructure error. This is an assisted continuation,
not a first-attempt or model-comparison score.

Progress: model-generated candidate-bound probe reached the initial HDU write.
Same-input output linked `_format_float`, Card serialization and write VerifyError;
the original short decimal input retained its short string. This is materially
more relevant than the prior successful raw-card parsing probes. The model's
normalization hypothesis is now grounded in an executed failing path, but a fix
preserving both requirements has not been produced or validated.

Stop:11calls/125,803tokens/139.297 agent seconds,27tools; total trial342s.
6/6 recovery actions used: initial saved-failure assessment plus5 source-evidence
reselections. Implementer evidence sizes56,177,52,137,49,760,49,760,49,760bytes,
limit48,000. Remaining20call/180k-token/600s global budget did not prevent nested
recovery-action exhaustion. No patch generation/new verification round; final
grading still ran on inherited candidate and failed.

Failure class: evidence selection can reduce source windows, but repeated selection
does not necessarily reduce fixed goal/diagnostic/controlled evidence overhead.
This resembles diagnostic request accumulation but is a separate proposal-request
builder; the previous compaction patch did not apply here. Next inspect exact
message component sizes, deduplicate proven repeated raw wrappers, retain current
failure and execution provenance, then replay saved selections with zero model
calls. Do not merely increase global budget or force model to repeatedly reselect.
Any claimed overhead cause beyond measured message sizes remains to verify.
