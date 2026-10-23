# Live acquisition micro-review v1

Evidence: `.keel/repair-review/acquisition-live-v1/results/report.json`,
`model-transcript.jsonl` and `trace.jsonl`. No task patch or acceptance run.

## Verified observations

The run stopped on Model-call budget exhausted, not wall-clock, token or transport
failure: four live requests and four live responses, 22,527 recorded tokens,
9 tools, 36.656 seconds. Five host dispatch reservations include the zero-provider-
usage saved reply. Source workspace unchanged; acceptance not executed. The stale
pending_provider_call=4 in the final report does not mean response 4 was absent;
all four replies exist in the transcript.

1. Call 1 planned literal searches. A guessed exact test signature produced no
   match because the actual signature has an extra fixture argument; automatic
   failed-test navigation had already located its definition at line 2020.
2. Call 2 requested formatter lines 1280..1325 and test lines 2020..2065.
3. Call 3 had the actual test body, including initial write, deliberate binary
   mutation and later warning expectations, but requested the formatter tail.
4. Call 4 received the remaining formatter and replayed earlier source windows.
   It again returned continue and requested the same 1325..1362 range already read.
   Budget prevented the next assessment. No final supported/refuted/insufficient
   inspection result or new proposal was produced.

## Judgment and limits

Automatic unknown-to-inspection routing and source delivery worked. Evidence was
not successfully integrated into a causal assessment. The response did not separate
setup, deliberately corrupted input and expected-warning phases of the test; it
repeated the formatter hypothesis instead. This is model interpretation/control
failure in this example, not proof that the function is unrelated or that a
particular source edit fixes the task. Host source is a frozen repository test,
not a certified copy of all official patched tests.

Increasing the four-call cap alone is not justified by this trajectory: the last
request already repeats covered source. Existing no-progress logic can stop only
after additional repetition, and the small review cap hit first. No causal repair
or acceptance improvement established. Original failed micro costs remain intact.

Next test a generic evidence-synthesis milestone: for each observed source window,
state what concrete question it answers, separate test setup/action/assertion and
expected errors, state how it changes the hypothesis, and distinguish missing
source from missing execution. A request for an already-covered range must name
what observation was not delivered or what new question it can answer. Use frozen
source and a short assessment to evaluate this contract before more long runs.
Do not encode this test's branch or repair into generic logic.
