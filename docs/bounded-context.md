# Bounded role conversations

## Contract

`agent.max_context_bytes` is an optional positive integer. Omit it to retain the
original history behavior for paired comparisons. When enabled, before each
model request Keel caps serialized messages plus the structured response schema
in UTF-8 bytes. It does not truncate task instructions, declare success, create
edits, or alter global model/tool/token/wall-clock budgets. Output remains
separately limited by `agent.max_output` and reserved by the existing budget
preflight. A byte cap is not an exact tokenizer or a guarantee that every model's
chat template fits `num_ctx`; provider context and output limits still matter.

The system instructions and initial role task are immutable. Old complete
action/observation exchanges are stored as `decision` receipts in that role's
ledger visibility scope. To fit the request, oldest exchanges become a linked
archive index, available via the existing `recall` tool. Index nodes point to the
exchange receipt and previous index. Neither receipts nor index facts satisfy
the tool-observation requirement for role completion. They grant no access to
other roles' facts or curator evidence.

The active memory message contains the index pointer, archived-turn count and
up to four recent failure/edit summaries. Older failures remain in the durable
chain; they are not all pinned in the live prompt. Summaries come from actual
tool outcomes, not another model. No full reasoning summary is generated.
Receipt observations and retained source remain untrusted data.

After a successful edit, old exchanges are archived before the next request so
stale source previews leave active history. The edit summary survives and the
model can inspect fresh source with existing tools. This is not a filesystem
lock: external concurrent modifications are not prevented. Workspace and exact
replacement checks remain authoritative.

If immutable task/instructions/schema plus the bounded memory cannot fit,
execution reports budget exhaustion before sending or charging a model request.
Compaction is not allowed to quietly remove the goal or permission constraints.

## Measurements and controls

`context_window` trace events contain `input_bytes_before`, `input_bytes_after`,
`archived_turns`, `total_archived_turns`, `source_changed`, and `limit_bytes`.
These describe the input assembly, not provider-measured tokens or quality.
Actual tokens remain in model-call budget records.

The exploratory Starlette runner defaults to 12,000 input bytes and records the
policy in `task.json` and `summary.json`. Use `--max-context-bytes` to change it,
or `--unbounded-context` to disable it. Hold model, per-role turns, task, output
limit and wall-clock budget fixed when comparing runs:

```powershell
python examples/run_starlette_upgrade_task.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9 --execute --max-seconds 450 --max-steps 5
```

For the control, append `--unbounded-context`. Different settings are retained in
artifacts; retries do not increase independent task coverage. No live success,
token saving or speed improvement is established by the implementation alone.

Four dedicated tests cover a 40-turn Unicode-safe serialization bound and receipt
chain, preserved immutable headers, stale preview removal, oversized-input
preflight, and a complete model-driven read/window/edit/verification flow.

## First live bounded run: no compaction triggered

Artifact: `.keel/upgradebench-agent/c8e11cbf66e04581a923c285af957c36`.
The 12,000-byte policy ran with five turns per role and a 450-second global
runtime limit. Scout used all five turns: two full-file reads followed by three
searches. No final impact analysis or edits were produced. The run correctly
reported `budget_exhausted` in Scout, rather than forcing a final summary.

Measured request inputs (including structured schema) were 3,654, 8,801, 9,034,
10,108 and 11,182 bytes. All five `context_window` events reported zero archived
turns, because the byte cap was never crossed. This run therefore establishes
policy instrumentation and honest turn exhaustion, not live compaction efficacy,
repair improvement or a causal performance regression. A smaller cap would be a
different experiment, not evidence that the current policy fixes action selection.

Do not repeatedly rerun the same case with arbitrary budget changes. Next build
a small frozen task/control set and compare model action capability while
reporting all runtime and context settings. Retain this unresolved attempt.
