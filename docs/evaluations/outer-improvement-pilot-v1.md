# Outer-improvement pilot v1 assessment

Evidence: `.keel/outer-improvement/pilot-v1/report.json`, `candidates.json`, each `case-*/trial.json` and receipt. All 16 completed arm receipts, proposal receipt, manifest digest, recorded scores and deterministic selection were checked without provider or Docker calls.

| Prompt | Grounded passes |
|---|---:|
| Incumbent | 2/4 |
| grounded_checking | 4/4 |
| evidence_first | 4/4 |
| separate_cause_testing | 4/4 |

The three candidates tie. The implementation retains the first maximum in proposal order; `grounded_checking` is a provisional tie-break choice, not a demonstrated superior candidate. The `rejected` field includes unselected tied candidates and must not be read as evidence that they are harmful or inferior.

Incumbent case-2 and case-4 both attempted `select_zero` but cited `original_failure` before any observation existed. This is a displayed probe ID, not an observation ID. Validation stopped the turn before execution. Case-2 also predicted the boolean expression backwards; case-4 predictions were correct. Thus the observed baseline failures chiefly reflect evidence-ID protocol errors, with one counterfactual-prediction error. They do not establish inability to choose a discriminating check. The candidate example executes `select_zero`, receives observation-1, and then correctly concludes B with the observed result cited. No protocol-error correction retry is present in this evaluator.

Reported aggregate usage: 33 model calls (one proposal and 32 solver calls), 18785 tokens, 32 child probe executions, 216.844 seconds. Tool count includes hidden A/B counterfactual executions used by the checker; it is not 32 model-selected experiments. Arm budget fields are cumulative shared-budget snapshots and must not be summed. Monetary cost was not calculated.

This real run qualifies model proposal → isolated execution → objective comparison → provisional retention. Feedback was a fixed developer summary; cases are four exposed synthetic cases in only two families; each condition was sampled once. It does not establish automated trajectory mining, repeated stability, independent transfer, production improvement or model-weight learning. Production remains unmodified.

Next: freeze all three tied prompts unchanged, make observation-ID instructions explicit and identical across arms, and test repeated controls plus new independently constructed case families. Separate protocol compliance, correct predictions and grounded diagnosis in reporting. Do not spend another run choosing among tied prompts on the same four cases or promote the winner on this evidence alone. Any protocol clarification is a new evaluator version and must retain this pilot unchanged.
