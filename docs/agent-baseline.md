# Fixed agent diagnostic baseline

`--feedback-from PREVIOUS_RUN_DIRECTORY` supports one explicit proposal follow-up
for a matching completed verification failure. It requires `--model-config`,
`--group real_compatibility` and no dependency evidence. The follow-up starts
from original source with prior patch/errors, links previous cost and uses a
fresh per-attempt budget; count both attempts together, not as independent tasks.
It is not a shared-budget automatic repair loop. See the
[Flask-WTF failure and follow-up](evaluations/upgradebench-flask-wtf-565-review.md).

For a controlled comparison of the existing one-call proposal and six-role
tool loop, use the [paired orchestration diagnostic](strategy-comparison.md).
The offline comparison preserves failed tasks and rejects mismatched inputs.

The suite diagnoses action execution before additional runtime tuning. It is
not UpgradeBench v1, a public benchmark or a three-real-task evaluation.

The default real case remains #1936. A second curated candidate can be selected
with `--case 2526`, requiring its own matching successful reproduction; see
[the HTTPX compatibility reproduction](evaluations/upgradebench-starlette-2526-review.md).
Each invocation selects one real case; synthetic controls remain a separate group.
`--case flask-wtf-565` adds a multi-file, second-repository diagnostic after its
[successful reproduction](evaluations/upgradebench-flask-wtf-565-review.md).
Saved tasks include `targets`; legacy single-file `target` remains supported.
Passing requires nonempty changes confined to the declared scope and the same
independent acceptance, rather than requiring every allowed file to be edited.
Proposal preparation checks source-window messages plus output schema against
the context byte cap and records `context_preflight`. This is not a token count
or an exact serialized HTTP-body size. Optional dependency evidence is collected
only during execution; runtime rechecks the complete input before inference.

## Tasks and controls

| ID | Group | Purpose |
| --- | --- | --- |
| short-version | synthetic_control | One constant edit with behavior preservation |
| long-version | synthetic_control | Same edit and acceptance after 400 padding lines |
| starlette-1936 | real_compatibility | Previously reproduced AnyIO API migration |

The two synthetic controls share semantics; they are not independent domain
coverage. Their results are reported separately from the single real task.
The real task supplies the affected filename, so this does not evaluate Compass.

All tasks use the same resolved Docker image from the successful reproduction,
CPU Ollama, context 4096, output 1024, 450 seconds per agent run, five turns per
role, 30 model calls, 60 tools, 180000 accounting-token budget, context handoff,
and 12000 input bytes. Baseline acceptance has a separate 90-second timeout.
Use `--unbounded-context` only as a separately identified control.

## Run

Prepare only (no model calls or Docker access):

```powershell
python examples/run_agent_baseline.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9
```

Run all three sequentially with the existing model:

```powershell
python examples/run_agent_baseline.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9 --execute
```

For a later model comparison add `--model <installed-ollama-name>`. There are no
automatic downloads or external API calls; model identity is read from local
Ollama before execution and checked after each completed task. A changed model
invalidates the affected result. Do not replace an installed model mid-suite.

Three agent runs allow up to 22.5 minutes of agent runtime, plus baseline and
preparation time. A heartbeat prints every ten seconds. Failures do not abort
later tasks; records are checkpointed before and after each attempt.

## Evidence and comparison

Under `.keel/agent-baseline/<id>`:

- `manifest.json`: fixed goals, source hashes, config, runtime source hashes and
  per-task comparison keys excluding only the model name.
- `tasks/<id>/template`: clean base-only input, no reference patch or Git history.
- `runs/<id>`: disposable repo, baseline, runtime result/trace/ledger and patch.
- `results.json`: every planned task, environment errors, executed failures,
  successful tasks, budgets and context/tool-call metrics.

Require matching comparison keys and runtime source hashes for a model-only
comparison. They differ for context-policy changes, so identify the changed
factor explicitly for runtime comparisons. The current script does not compute
paired significance or aggregate quality across heterogeneous groups. Repeated
attempts do not become additional independent tasks.

Base acceptance must reproduce the expected failure before model execution.
Final success requires real model calls, runtime audit success, exactly the
expected source file changed, and Docker acceptance. Starlette additionally
requires the same two case identities and package versions as its reproduction.
Environment errors stay in planned counts, separately from executed tasks.
`task_passed` is never inferred merely from a model summary or generated diff.

Four tests cover frozen model-only controls, separate group denominators,
noninvented context metrics, and actual base-fail/reference-pass for both synthetic
controls. The suite has been prepared locally; no live suite success or stronger
model comparison has been established yet.

## First live suite and protocol controls (2026-10-15)

With `keel-chat:latest` digest
`d8e45768208394715b5febaea6dfe20f1b9d533d27044c2c0fbee4ef9410915a`,
all three executed tasks exhausted Scout's five turns without edits. The two
synthetic controls passed 0/2; the real task passed 0/1. No environment errors
were reported. These small, heterogeneous groups are not a public resolve rate.

| Task | Agent seconds | Tokens | Calls | Peak input bytes | Archived turns |
| --- | ---: | ---: | ---: | ---: | ---: |
| short-version | 71.312 | 3362 | 5 | 5311 | 0 |
| long-version | 104.907 | 6108 | 5 | 9730 | 0 |
| starlette-1936 | 133.641 | 8391 | 5 | 11182 | 0 |

Every Scout performed two full-file reads and three searches. Context compaction
never triggered, so this suite does not measure its causal benefit. The common
role-completion failure appears even on the simplest control, before repair.

`python examples/probe_agent_protocol.py` separates protocol choice from simple
patch generation without executing model-generated code. Live artifact:
`.keel/protocol-probes/63be5e23dd8a45e7b25c25265b0f396e`.
Both nested-tools-first and flat-final-first schemas returned `final` when
explicitly told the required evidence was complete. Both incorrectly described
the unchanged source as already changed, reinforcing that a summary is not an
execution record. A separate typed old/new proposal produced an exact correct
patch for the synthetic constant control. No code was applied or executed.

This rules out a universal inability to emit `final` under the current schema;
it does not prove either schema works reliably in long agent histories. The
patch probe demonstrates only one simple generation case, not autonomous repair.
The next useful experiment is an explicit bounded edit-proposal path compared
with free tool-loop orchestration under the same tasks and acceptance, rather
than further unpaired prompt tweaks or more retrieval features. A stronger-model
comparison remains pending. Preserve these failed runs in the baseline.

The bounded edit-proposal experiment is now available via `--strategy proposal`;
see [its contract and evidence](patch-proposals.md). It reuses sources and Docker
acceptance with deterministic file-localized Scout/Planner and one model proposal.
The original `tool-loop` remains default; strategy is recorded in both manifests
and results. This is not a model-only comparison.

The proposal control rerun at
`.keel/agent-baseline/1862e6beaca44d5088b7c911aca3d501` passed 2/2 synthetic
controls with one model call per task and matching source, goal, image,
acceptance, budget and model identity relative to the original failed controls.
No real task was selected in that rerun. See the proposal contract for metrics
and limitations; do not merge its result into the earlier three-task suite.
