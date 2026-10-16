# Explicit repair completion and observed baseline evidence

The runtime previously treated any Implementer final string as a completed work
item. The verifier still rejected unchanged failing code, but a statement of
future intent wasted the role's opportunity to perform the task. This is an
interaction contract issue, not a reason to weaken independent verification.

## Opt-in contract

`agent.require_change: true` means each Implementer item must produce a nonempty
net modification to at least one declared file through a successful replace in
that same session. The session hashes declared source at entry and compares
edited files before accepting a final. Edit-and-revert does not qualify; merely
changing prose or making a rejected edit does not qualify. Wrong final types or
missing net change receive ordinary tool/protocol feedback within existing turn,
token, tool-call, model-call and wallclock limits. No extra model retry budget.

Default is false. Inspection/no-change tasks can still finish without edits.
Scout and Planner receive the setting but do not require changes themselves.
The guard proves neither correctness nor sufficiency. A meaningless net edit can
satisfy this condition and must still pass verifier/audit. Host hash bookkeeping
does not expose an additional model tool. Proposal paths already reject all-noop
edits; their existing independent checks remain unchanged.

This deliberately does not require that every declared file be changed, nor
does it force a particular repair or inspect summary wording to infer success.
Protected-path checks apply before writes, and the final scope audit remains.

Tests cover intent-only final followed by bounded recovery, edit-and-revert
rejection without running verification, and a legitimate no-change task with the
flag disabled. Agent (29), localization (8), runner (5), proposal (13), and
native/LangGraph orchestration (13) tests passed: 68 relevant tests.

## Next development trial

Preparation `httpx-1588-localized-errors-v1` opts into both baseline error evidence
and the repair contract. Preparation-only flags are frozen; they cannot be
enabled at execution. No new role, shell permission, model, acceptance case,
budget increase or reference repair has been introduced. Baseline evidence is
actual pre-edit case error types/messages, not a previous patch or gold code.

```powershell
python examples/run_transition_task.py --package .keel/task-packages/httpx-1588-v1 --model-config .keel/model-openai.json --strategy localized-proposal --baseline-feedback --require-change --output .keel/transition-trials/httpx-1588-localized-errors-v1
python examples/run_transition_task.py --output .keel/transition-trials/httpx-1588-localized-errors-v1 --execute
```

The first command has already been run locally; no provider call occurred.
Execution must preserve the original failed compact-map patch and all earlier
runs. A future pass would be one observed development task, not proof of runtime
superiority, an independent benchmark or a causal ablation of both flags. Both
simple and multirole arms would need the same evidence/completion contract for
a fair later comparison. No additional live outcome is claimed here.
