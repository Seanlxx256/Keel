# Failure-guided prompt replay v2 assessment

Evidence: `.keel/outer-improvement/feedback-replay-v2`. Verified six completed trial receipts, manifest/proposal receipts, all scores recomputed from saved observations/final labels, deterministic selection, migration source-file identities and byte-identical reuse of v1's paid proposal. No new provider or Docker calls during this review.

| Exposed development condition | Incumbent | diagnostic_probe_precision |
|---|---|---|
| routing A | pass | pass |
| snapshot B | fail | fail |
| counter B control | fail | pass |

Total grounded passes: incumbent1/3, candidate2/3, no per-case regression. The provisional gate therefore retains the candidate. Both arms have correct counterfactual predictions on two of three cases and no protocol errors. The measured difference is the final label on counter B, not improvement in prediction accuracy or the snapshot family.

Counter incumbent correctly predicts A=false/B=true and receives true. Its explanation rules out A and supports B, but structured conclusion is A. The candidate returns B consistently with the same kind of observed evidence. This is one paired sample, not a demonstration that the guidance causally or reliably fixes label consistency. Counter was passed by all arms in the previous validation, showing variability even in a preservation control.

Snapshot remains unresolved. The candidate claims both hypotheses predict stored_copy=true, overlooking mutation before the check. It then treats original_failure as discriminating although the checker observes false under both causes, and concludes A on a B fixture. This is semantic state/prediction misunderstanding, beyond pure field serialization. Merely requiring consistency does not guarantee correct interpretation of hypothesis behavior.

Aggregate accounting: 15 model calls, 11328 tokens, 16 fixed child executions,105.782 seconds cumulative runtime. This includes the original failed launch's one proposal call/1830tokens/7.313seconds. The migrated run added14solver calls/9498tokens; it did not regenerate the proposal. Offline validation before migration was not a provider call. Old failed results remain unchanged; no production promotion.

The loop now has one real failure-derived proposal and provisional development selection, with developer-engineered validation/migration assistance. Cases and trajectories were shown to the proposer; they are not independent selection. No autonomous production improvement, model training or general repair benefit is established. Next freeze this candidate rather than expand claims. Prioritize the separately audited typed interception/recovery mechanism; if measuring this prompt further, use new state-sensitive cases and predeclared repetitions with the unchanged checker.
