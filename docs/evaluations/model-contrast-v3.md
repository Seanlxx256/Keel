# Diagnostic model contrast v3, 2026-10-23

One developer-assisted exposed case, one run per model; same frozen inputs and
limits as v2, identical request-view compaction implementation for both models.
No patch generation or official acceptance. V2 failures/costs remain separate.

| Measure | GPT-5.4 mini | GPT-5.4 |
|---|---|---|
| Calls / tools | 3 / 2 | 3 / 2 |
| Reported tokens | 22,540 | 23,218 |
| Seconds | 29.187 | 62.094 |
| Child probes | Both import failures | Both completed on hashed candidate |
| Final assessment | unknown | supported (model claim, not host certification) |
| Exact failing initial HDU write exercised | No | No |
| Accepted repair | Not attempted | Not attempted |

Sources: `.keel/repair-review/model-contrast-v3/{mini,full}/results/report.json`,
`probe/ledger.sqlite` facts 1--5 and `probe/trace.jsonl`.

The context fix permits call3 in both real runs without raising the32k cap.
Mini again manually inserts a partially initialized module; its second script
changes values but keeps the same failing loader mechanism. Both fail importing
CARD_LENGTH before running the intended experiment. Its unknown conclusion
acknowledges missing execution evidence; the claimed long-string direction is
not established. Byte-different scripts are not necessarily different strategies.

Full uses qualified imports and executes candidate card/header hashes. Its
over-precise decimal raw card preserves original text during verification. Its
second raw21-digit integer parses as int, preserves text, and passes verification;
separately converting that integer to float and calling the formatter produces a
different string. These are valid narrow observations but not a controlled
float-regeneration causal comparison: the second raw card is an int, and neither
probe triggers the actual failing write/fix path. Therefore the final supported
claim about the regression mechanism is stronger than the evidence. It has not
demonstrated the root cause or a repair preserving both requirements.

Observed advantage: successful probe execution (also seen in v2). Remaining
weakness: experiment relevance and interpreting negative/indirect evidence.
Full takes longer and similar tokens in this run; no broad cost/quality claim.
Next compare a generic failure-path coverage/claim-evidence check or exact failing
operation acquisition under frozen conditions, rather than add another broad
prompt or assume supported means resolved. Do not encode the case's repair.
