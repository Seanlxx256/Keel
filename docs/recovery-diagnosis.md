# Evidence-based recovery diagnosis

Adaptive recovery now supplies the Critic with actual base-to-current source diffs,
structured failed verification, recent recovery actions, and the previous two validated
diagnoses. Diffs are bounded to 6000 characters overall and 2000 per file; omitted
files and characters are explicit. Workspace reads consume the shared tool budget.

The Critic must return action, reason, hypothesis, evidence, next_check, and
previous_attempt_assessment. These are concise externally checkable claims, not
private reasoning. The host validates field shape and limits, not diagnostic truth.
The next role receives the diagnosis with an instruction to check it against current
source before editing. It can still make an incorrect diagnosis or ignore an instruction;
this is not proof that the proposed check was executed.

An ineffective proposal triggers fresh model-selected source evidence before another
proposal. All retries consume existing recovery actions and global budgets. Protected
tests and operator write roots remain enforced. Diagnoses are retained in the recovery
report and ledger. Structured verification fingerprints distinguish observed failures
without including elapsed-time noise from full logs.

No task-specific fixes or reference patches are used. Local deterministic tests cover
multi-round history, actual diff handoff, ineffective-proposal recovery, write permissions,
and budget exhaustion. Real-model effectiveness remains unmeasured for this version;
old benchmark results are not replaced. Rerunning previously debugged tasks is a
development check, not a held-out score or controlled recovery-benefit estimate.
