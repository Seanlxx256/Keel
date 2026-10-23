# Optional diagnostic probe pair v1

Evidence: `.keel/repair-review/probe-pair-v1/results/report.json` and per-arm
model-transcript.jsonl. Original results remain unchanged.

| Arm | Calls | Tokens | Seconds | Tools | Final conclusion | Probe used |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Read only | 1 | 5902 | 9.750 | 0 | unknown | false |
| Probe available | 1 | 5909 | 18.204 | 0 | unknown | false |

Two new calls /11,811 recorded tokens total. Both arms answered immediately.
Both source snapshots unchanged, no patch application or acceptance. Docker image
was resolved to a local ID, but no diagnostic container execution occurred; image
availability is not live validation of the sandbox/interpreter/probe wrapper.

## Interpretation

No distinguishing execution observation was obtained. The predeclared primary
success criterion was not met. Tool availability alone did not improve this case;
do not promote probe support to default repair or claim runtime probing failed.
This is evidence about voluntary action selection/early abstention, not a valid
comparison of reasoning with versus without actual execution observations.

Both answers still fail to clearly separate initial valid write, manual corruption
and subsequent warning check. The probe arm's claim that the lowercase exponent
string is legal is unsupported and conflicts with the reported verification error;
its unknown conclusion must not be mistaken for an otherwise correct causal
explanation. Exact source IDs do not certify interpretation.

## Next decision

Do not rerun this optional-tool pair unchanged or merely add call budget. Separate
(1) voluntary tool selection from (2) probe design/execution and evidence use.
A next capability test can require one model-designed discriminating experiment
before a final answer, or an explicit concrete execution blocker. Declare this as
a different, mandated-action policy, not the same optional-tool comparison. Do not
provide the task's probe or repair answer. Preserve the present abstention baseline,
keep mini and finite budgets, and inspect what source actually executes. If the
model cannot design a useful probe or use its output, do not add the policy to
production. No next paid run was dispatched during this review.
