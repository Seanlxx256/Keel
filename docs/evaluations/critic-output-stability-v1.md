# Frozen Critic output-cap check, 2026-10-23

All3predeclared samples used identical archived runtime, prompt/schema/model and
1024output cap,1call each,60s timeout,48k declared token reservation. No tools,
patches or acceptance. Evidence: critic-stability-v1/trial-{1,2,3}/results/summary.json.

| Sample | Result | Input tokens | Output tokens | Seconds |
|---|---|---|---|---|
| 1 | Protocol completed | 9494 | 1013 | 25.187 |
| 2 | Truncated, finish_reason=length | 9494 | 1024 | 24.328 |
| 3 | Protocol completed | 9494 | 943 | 21.406 |

Total31,462tokens. Sample2 reports refusal_present=false,content_present=true,
and stops in the previous-attempt assessment mid-sentence. The output cap is
therefore a verified failure mechanism in this sample; no timeout/authentication
or input-cap rejection. Sample1 barely fits11tokens below cap. This establishes
fragility of protocol completion under the1024cap on this request, not failure
of the whole repair algorithm or a general2/3success rate. Valid JSON is not
correct diagnosis. V5 finish reason was not preserved; do not retroactively claim
certainty that its superficially identical failure was length-based too.

Next preregistered study critic-stability-v2 reuses the exact same runtime archive,
model config and messages/schema, changes only max_output to2048;3independent
samples, same48k total-token reservation and60s per sample. No automatic retries
or optional stopping. Plan/snapshot hashes verified. Output-budget improvement
must be measured, then explicitly migrated into the full runtime before separate
end-to-end repetitions. The new launcher preserves caller directory with Push/Pop.
