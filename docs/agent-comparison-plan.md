# Next experiment: equal-access orchestration comparison

Status: design only. No new inference, independent scores or selected thresholds.

## Question

Does separating localization, planning and implementation improve repair outcomes
relative to one bounded tool-using session, when both have the same model,
workspace, tools, source access, verifier, audit and global resource limits?

The observed HTTPX failures motivate the question, but HTTPX is a development
case. Its repeated runs are not independent samples. Operator-localized proposal
results cannot answer this question because the model receives selected files
and windows instead of doing autonomous repository search.

## Two arms

- Multirole: existing Scout, Planner and per-item Implementer; deterministic
  Verifier/Auditor and failure recording remain unchanged.
- Single session: one model session can search, read, propose and execute scoped
  changes; same underlying tools and deterministic verification/audit. No curator
  localization, gold diff, reference file list or model-specific repair hint.

Both arms must receive the same task text and fresh base workspace. Both need the
same task-level Python source scope. The single-session adapter must not bypass
protected paths or workspace permissions. Any difference in source/tool access
must be corrected before results can be called an orchestration comparison.

## Completion contract and accounting

For a task explicitly requiring a source repair, define before execution that a
final requires a nonempty net diff in the permitted source scope. Tool success
alone is insufficient: edit-and-revert is not a completed repair. An invalid
final receives bounded feedback, charged to the same global model/turn budget.
Apply that contract to both arms. Do not silently require changes for all task
types; no-change tasks need a separate explicit contract.

Hold the model configuration, total input/output limits and global call/tool/
token/wallclock budgets constant. Account for Scout and Planner in the multirole
total. Record role limits as an additional experimental constraint rather than
pretending equal global budgets imply equal usable budgets. Use an equal total
turn allowance or report a separate role-cap ablation before causal claims.

## Preparation and execution gates

1. Implement the single-session adapter and shared completion contract offline.
2. Test early final, allowed edit, rejected edit, edit-and-revert, no-change task,
   protected-file attempt, budget exhaustion and independent verifier rejection.
3. Verify both arms use identical source/tool scopes and preserve raw artifacts.
4. Freeze all tasks, both configurations and implementation hashes before paid
   execution. Keep model response identity and all failures, including environment
   errors. Do not substitute tasks after observing results.
5. Development cases may validate wiring, but outcome-driven adjustments invalidate
   held-out status. Independent tasks require separate prior preparation.

Report paired task passes, no-edit completions, rejected edits, verification
failures, model tokens/calls and wallclock including common baseline costs.
Repeated seeds do not increase task coverage. No significance claim from a few
tasks. Preserve original all-task denominators and disclose environment errors.

Do not implement automatic Critic retries, new retrieval strategies or higher
budgets concurrently: they would confound the orchestration comparison.
