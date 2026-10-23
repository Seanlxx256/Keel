# Orchestrator-controlled diagnostic closure

Status: proposed, 2026-10-22. Audit only; mechanisms below are not implemented.

Update: an opt-in diagnostic_execution bridge is now locally tested in runtime.
It reuses the investigator/executor before a pending Critic check reaches patch
generation. Ledger/hypothesis/state redesign below is still proposed; no new live
repair benefit established by this integration.

## Verified current gaps

- diagnostic_probe.investigate ends on explicit JSON answer/blocked actions,
  rather than an implicit plain-text response. Scout has read/search/probe access.
  Actual candidate execution previously succeeded. Tool permission absence does
  not explain the latest zero-action result.
- Fresh-execution gating protects answer, but blocked validates text/citations and
  unknown only. targeted-feedback-v2: one call, zero tools, unsupported blocker.
- runtime.critic_phase passes textual next_check via active_goal to subsequent
  roles. It has no uniform executable-check completion receipt. Experimental probe
  review is separate from default repair and is not automatically enabled there.

## Proposed shared contract

Model proposes; host computes transitions. Reuse existing ledger, budget/trace,
ToolGateway, CommandRunner, source provenance and verification feedback.

Records:
- Hypothesis: id, question_id, statement, status, support/refute predictions,
  evidence_ids, update_reason. Host checks distinct nonempty predictions; meaning
  still needs semantic review.
- Check: id, question_id, hypothesis_id, registered tool, executable arguments,
  expected observations, pending/running/completed/failed. No host-generated
  task-specific script from free text.
- Evidence: host-owned ID, call ID, run/turn, question ID, source manifest hash,
  test IDs, input hash, failure signature, environment/tool identity, raw result,
  outcome/provenance. Preserve historical costs and distinguish historical evidence.

Keep prior rationale in traces. Send compact active state and relevant raw evidence
instead of repeated reflection essays; do not blindly remove useful history.

States and predicates:
- REPAIR_VERIFIED: fresh matching source/input/environment verification, fixed
  target and preservation test universe, no missing or new failures.
- DIAGNOSIS_READY: separate from repair; no claim that diagnosis is correct merely
  because a probe ran or its ID was cited.
- BLOCKED_VERIFIED: typed obstacle bound to actual call/result or host preflight
  denial. Forbidden actions need not be attempted. Invalid model arguments are
  action errors; ambiguous causes remain unclassified.
- ACQUIRE: absent evidence becomes a request for executable check specification.
  Validate and dispatch it; a proposed check remains pending until executed.
- Unsupported terminal claims get bounded feedback, then UNRESOLVED if repeated.
- Budget exhaustion, cancellation and executor error are explicit non-success exits.

```text
while budget remains and not cancelled:
    proposal = model(active_question, active_state, relevant_raw_evidence)
    if proposal.check: validate_execute_record(proposal.check)
    elif verified_obstacle(proposal): stop(BLOCKED_VERIFIED)
    elif fresh_acceptance_passes(): stop(REPAIR_VERIFIED)
    else: bounded_feedback(unmet_predicates, pending_checks)
stop(explicit_non_success_reason)
```

This pseudocode describes repair, not read-only review. Judge claim/evidence support
only after deterministic checks; judge output remains fallible, not acceptance.

## Failure identity and stagnation

Prefer structured pytest/JUnit/harness reports: test ID, phase if available,
exception, frames and raw offsets. First versus later statements within a test
are not necessarily pytest phases. Source mapping may be needed; ambiguous or
truncated evidence stays unknown. Existing state/error fingerprints are not
already normalized semantic signatures.

Reuse matching verification until code/input/environment changes; do not rerun
all tests each reasoning turn. Explicit nondeterminism experiments may repeat.
Hash normalized tool/arguments/source/input for exact duplicates; semantic
hypothesis equivalence is not solved by hashing. Record justified repeats.
Stagnation can offer registered reproduction, comparison, source inspection and
bounded tracing under current permissions/budgets. Bisection requires suitable
versions and a runnable predicate, not a universal fallback.

## Delivery and evaluation order

1. Shared terminal-policy module and deterministic tests: false missing-evidence
   blocker, real denial, bad arguments, stale evidence, pending checks, executor
   failure, budget and cancellation. Experimental review integration first.
2. Bind source/input/environment/failure identity using current ledger/feedback.
3. Executable check handoff and hypothesis records, then explicit runtime rollout.
4. Frozen cross-repository checkpoints plus held-out cases and true-blocker controls.
   First compare automatic execution of model-proposed checks with baseline.
   Oracle evidence/hypotheses are assisted arms. Retain mini; model swaps need
   separate authorization. Predeclare repeats and aggregate cost cap.

Report executed valid checks/valid proposed checks; duplicate actions/dispatched
actions; correct updates/labeled contradictory observations; false blockers/blocker
claims; detected true blockers/labeled true blockers; fresh verified repairs/all
assigned cases; diagnosis steps, time and cost. Also report invalid proposals and
coverage. Protocol validity alone is not success. Exposed case regressions do not
establish general improvement; held-out validation is still required.
