# Localized patch proposals

Opt-in `mode: proposal` removes free role navigation from this diagnostic path,
retaining model-generated edits and independent verification. Configure
`proposal: {"files": ["app.py"], "queries": ["API_VERSION"]}` alongside normal
goal/model/agent/budget/execution/acceptance settings. Explicit work items cannot
be combined with proposal mode.

Scout and Planner are deterministic here: operator-supplied files and literal
query anchors establish scope. Scout checks writable-path policy, reads source,
records hashes, and selects the first 40 lines plus eight lines around matches,
merging overlapping windows. If input exceeds the context byte cap it fails
before a model call, rather than silently losing windows. No reference patch or
new API name is supplied. This does not evaluate autonomous exploration/planning.

Implementer makes one proposal request for 1..8 exact `path`/`old`/`new` edits
and a summary. No tool loop, automatic retry or summary-based success exists.
Before the first write, the host validates the entire sequence against shadow
copies: declared scope, current source hashes, unique nonempty matches, actual
changes, Python syntax and static audit invariants. Application uses existing
workspace replacement checks and budgets, followed by final diff auditing and
independent acceptance. Plain JSON providers receive the same host validation.

This is not an atomic filesystem transaction: external races or I/O failures
during application can still leave partial output, captured in failure artifacts.
Agent/MCP processes stay on the host; only Docker verifier commands are isolated.

## Compare on the existing suite

```powershell
python examples/run_agent_baseline.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9 --strategy proposal --execute
```

Default `--strategy tool-loop` retains the original path. Sources, goals, output
cap, global budgets, model settings and Docker acceptance stay fixed. Proposal
mode changes orchestration and evidence presentation together; it is not a
model-only or single-prompt-factor comparison. Its comparison keys differ.
Keep synthetic controls and real tasks grouped separately.

## Evidence

`examples/proposal_edit_control.py` succeeded with real local `keel-chat`:
one model call, 290 reported tokens, 12.563 runtime seconds, actual constant edit
and successful local text-only acceptance. Artifact:
`.keel/proposal-controls/69a6db2be73a424bbde317fba97e739a`.

Generated source was not executed. This is shorter than the suite control and
uses different acceptance/budgets, so it establishes no paired speedup, Docker
success or real repair. The proposal suite is prepared at
`.keel/agent-baseline/890420f0fbe74893b50c4b2a54c178b4`; live suite results remain
pending. Eight tests cover one-call execution, batch preflight, scope, freshness,
syntax, protected paths, input limits and Verifier rejection of wrong repairs.

## First Docker suite: redundant preservation entries

Artifact: `.keel/agent-baseline/8689d8d895374b8f8767563b48d4efbd`.
All three proposals failed preflight, so synthetic controls remained 0/2 and
the real task 0/1. Each used one model call. Runtime seconds were 16.422, 18.172
and 28.813, respectively; no edits were applied. Lower call counts did not
establish successful repairs.

Archived proposal inspection identified distinct causes. Both synthetic controls
contained the correct constant replacement plus an identical old/new entry for
the preserved greeting function. Rejecting that redundant preservation entry
invalidated the otherwise useful batch. The Starlette proposal contained only
unchanged text, and its old snippet omitted actual source content, so it remains
invalid regardless of preservation handling.

Normalization now ignores an identical old/new entry only after scope validation
and an exact unique match against the shadow source at that point in the batch.
It never applies or counts that entry as a change. Fabricated or ambiguous old
text still invalidates the entire batch before writes. At least one effective
edit is required. `proposal_validated` traces and a ledger record include proposed
and effective counts plus ignored indices. Error messages distinguish empty old
text, match counts and all-unchanged batches. No fuzzy matching, newline repair
or automatic semantic fix is introduced.

Eleven proposal tests pass, including valid change plus preservation, all-noop
rejection and fabricated preservation invalidating an otherwise valid batch.
The first suite's outcomes remain failures; success with normalization needs a
new run. Target only the two synthetic controls first:

```powershell
python examples/run_agent_baseline.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9 --strategy proposal --group synthetic_control --execute
```

Group selection exports and counts only selected tasks, not a completed full
suite. The unresolved real task is not silently counted as passed or discarded
from its earlier recorded results.

## Verified control rerun

Artifact: `.keel/agent-baseline/1862e6beaca44d5088b7c911aca3d501`.
Both synthetic controls passed Docker acceptance with only `app.py` changed.
Each used one model call; the short task reported 365 tokens and 16.859 agent
seconds, the long task 581 tokens and 18.062 seconds. No environment errors or
compaction events occurred. This run selected controls only and evaluated no
real compatibility task.

Manifest inspection against the original free-loop run
`.keel/agent-baseline/6c10aaf64a3f4666bba8771c2737b3e5` confirmed equal source
hashes, goals, Docker image, acceptance commands, global budgets and model
configuration. Model digest also matches. Original controls both failed in
Scout after five model calls; the proposal controls now pass with one call each.
Orchestration, evidence presentation and host normalization changed together,
so this is a small paired strategy comparison, not an isolated component effect,
a generalized speedup or a production success-rate estimate. Each task has only
one observed run per reported configuration.

The original proposal controls at `8689d8d895374b8f8767563b48d4efbd` produced
correct changes plus preservation entries and failed validation; the rerun's
success establishes the usefulness of the explicit preservation normalization
under these controls. Starlette remains unresolved and is not included in 2/2.

Next investigate target-dependency API evidence for real migrations. A model
guessing an API name is not a substitute for retrieving that API from the fixed
dependency environment. Such evidence must be obtained independently of gold
patches and labeled as a separate experimental input.
