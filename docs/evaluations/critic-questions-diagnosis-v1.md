# Explicit Critic questions: preserved pair review

Plan: .keel/repair-review/critic-questions-pair-v1/plan.json.
Both paid raw responses were preserved. No paid retry was performed during review.

| Arm | Tokens | Seconds | Original status |
|---|---:|---:|---|
| Previous prompt | 5,098 | 11.594 | completed |
| Explicit questions | 6,023 | 10.859 | failed: evidence length 1,023 > 1,000 |

Total 11,121 tokens, two calls. The new arm is valid JSON with all six required
fields, but violates the frozen character bound. Do not truncate it, raise the
bound retroactively, mint a completion receipt or replace the failed result.
offline-review.json records field lengths, source hashes and original status.

Qualitative reading of the failed raw response shows the requested labels and
support/refutation predictions, but the LOCATION text still asserts failure in
the later warning-mode rewrite without the call frame establishing that phase.
It even says the exception tail cannot establish the path while treating the
rewrite phase as known. The original full test log marks the initial valid write
as failing. Thus checklist compliance is not causal correctness. The prior prompt
also remains speculative; neither response establishes a verified repair.

Developer correction: shared validate_critic_decision now reports precise missing,
invalid-type and overlength fields in runtime and frozen review. Frozen review
persists validation_error beside raw_response. The live prompt emphasizes a
1,000-character hard limit with a 700-character target; bounds are unchanged.
This is future error clarity and output guidance, not recovery of the historical
failed arm. Tests include the exact 1,023-character boundary and no-paid-retry path.

Next priority remains preserving the failed caller frame with exception evidence,
then checking whether the diagnosis uses it. More labels alone did not establish
improvement. No new full repair attempt is justified by this pair.
