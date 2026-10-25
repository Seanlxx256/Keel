# Outer prompt validation v2

All 40 trial receipts, proposal receipt, manifest digest, metrics and selection recomputation verified from `.keel/outer-improvement/validation-v2`. No new model or Docker calls were made during inspection.

| Arm | Grounded pass | Correct final label | Protocol failure |
|---|---:|---:|---:|
| incumbent | 6/10 | 9/10 | 0 |
| grounded_checking | 5/10 | 7/10 | 0 |
| evidence_first | 5/10 | 9/10 | 0 |
| separate_cause_testing | 3/10 | 7/10 | 0 |

No candidate improved over the incumbent in this run. Keeping the incumbent is consistent with the gate; this is a successful rejection outcome, not evidence of prompt improvement. Small, related synthetic cases and only two repetitions do not establish statistical superiority of the incumbent. The shared evidence contract changed between pilot and validation, so cross-version gains cannot be attributed solely to that clarification.

By family across arms and repetitions: counter control 8/8 grounded passes; routing 11/16; snapshot 0/16. Snapshot nevertheless has 11/16 correct final labels. Its main scored failure is incorrect pre-execution counterfactual booleans, not uniformly wrong final diagnosis. Grounded pass intentionally requires correct prior predictions plus a correct conclusion citing that observation. Reporting only pass would hide this distinction; changing the requirement after observing failure would change the experiment.

Examples: repeat-1-snapshot-B-incumbent writes a rationale describing A=false/B=true but emits predicted_A=true/predicted_B=false. After observing true it correctly concludes B. repeat-1-routing-A-grounded_checking emits conclusion B while its explanation says the observation contradicts B and supports A. These demonstrate observable structured-field/explanation inconsistencies; they do not reveal hidden reasoning or establish why generation produced them.

Cost: 92 model calls, 61997 reported tokens, 104 fixed child executions (including checker counterfactuals), 636.235 seconds. No production update.

Next development step: use this newly observed failure class as feedback for a new bounded proposal round, asking for general structured prediction/decision consistency improvements rather than manually supplying business answers. Freeze existing results and scorer. Treat these validation cases as exposed development data from now on, and require fresh selection cases for a subsequent improvement claim. A narrow replay can distinguish field mapping mistakes from conceptual mistakes before paying for another full matrix. Do not rerun the same 40 trials unchanged or increase budget as the default response.
