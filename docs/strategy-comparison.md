# Paired orchestration diagnostic

## Follow-up protocol diagnostic

Tool-loop rerun `33d0bd50bfaf4c88b9c0db8252a6ee60` still exhausted five
Scout turns: 9137 tokens, 38.750 runtime seconds, no edits. The ledger shows
one bare summary/files response, successful `read_file`, invalid 1..260 window,
successful 1..80 window, then invalid 80..160 window (81 inclusive lines).
Two turns were archived; there is no evidence that archiving caused failure.
The first prompt change did not eliminate envelope mistakes or produce task
success. The model can repair this task through proposal, but tool-loop has
not yet demonstrated useful orchestration on it.

Window contracts now specify inclusive bounds and end <= start + 79 in both
the catalog and argument schema description. Rejection gives the exact legal
range for the supplied start and pagination guidance, without clamping or
executing an invalid request. Suite metrics expose protocol/tool errors and
failed gateway calls separately from the terminal budget category. Trace errors
include exception type, with details retained in the referenced ledger fact.
No automatic paid rerun or increased turn budget accompanies these changes.

## First paired observation (2026-10-15)

Saved pair: proposal `e579fa1e9dfd4180885d0f4db1d97061`, tool-loop
`e32e077e962f435b8105a5e1d8172a51`, under `.keel/agent-baseline/`.
The offline comparator accepted matching sources, shared configuration,
implementation hashes and configured model identity. Both disabled dependency
evidence. The report is `.keel/strategy-comparison-first.json` (local artifact).

| Strategy | Outcome | Calls | Reported tokens | Runtime seconds |
| --- | --- | ---: | ---: | ---: |
| proposal | passed curated Docker acceptance | 1 | 1185 | 12.250 |
| tool-loop | Scout turn budget exhausted; no edits | 5 | 6885 | 40.031 |

Inspection of the tool-loop ledger and trace identified three bare Scout
`summary/files` responses rejected for missing the `final` envelope, followed
by one successful `list_files`, then an invalid 260-line `read_lines` request
(limit 80). No source read succeeded. This is protocol/evidence acquisition
failure before repair, not evidence that the model cannot generate the patch.
The final role budget error hides the earlier actionable failures unless the
ledger is inspected. Tool attempt counts include failed gateway calls, whereas
budget tool calls count the operations that reach workspace charging.

The agent prompt now explicitly distinguishes the final value from its action
envelope, explains host-interpreted JSON tools, includes a tool-call example,
and repeats the line-window cap. Invalid-envelope feedback supplies the exact
action shapes and the outstanding evidence requirement. No output is silently
normalized; evidence gates, permissions, turn limits and acceptance remain
enforced. A regression test exercises bare-output rejection, real source read,
wrapped completion, real edit and independent acceptance. Live improvement
after this prompt change is unmeasured. A rerun is a diagnostic intervention on
a previously seen task, not fresh coverage; rerun both sides on this revision
if exporting another strict paired comparison.

The first user-reported OpenAI Starlette attempt passed the curated two-case
Docker acceptance with only `starlette/testclient.py` changed: one call, 1485
reported tokens, 12.422 runtime seconds and 15.531 seconds including baseline.
Requested model: `gpt-5.4-mini`; reported model: `gpt-5.4-mini-2026-03-17`.
This observation used dependency evidence and has not been independently
inspected here. It establishes neither a resolve rate nor a runtime benefit.

The next diagnostic compares the existing simplified one-call `proposal` path
with six-role `tool-loop`. Both retain Keel policy, validation and Docker
acceptance; this is not a no-runtime baseline. Source, goal, configured model,
acceptance, limits and implementation must match. Evidence presentation and
allowed interactions differ by strategy, so this is a bundled workflow
comparison, not an isolated role/ledger/cache/audit ablation.

Run both on the same checkout, with the same current-session credential and
Docker running. Each command creates a fresh artifact directory. These are
paid API executions; tool-loop can make up to 30 model calls under the existing
450-second runtime budget, unlike the one-call proposal. Token limits are not
dollar spending caps. Do not change code or config between commands.

```powershell
python examples/run_agent_baseline.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9 --strategy proposal --group real_compatibility --model-config .keel/model-openai.json --execute
python examples/run_agent_baseline.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9 --strategy tool-loop --group real_compatibility --model-config .keel/model-openai.json --execute
```

Do not add `--dependency-evidence`: only proposal currently supports it.
The earlier evidence-backed successful run is not an eligible paired control.
To inspect preparation first, omit `--execute` from both commands; preparation
does not call the model. Prepared reports cannot enter the comparison.

Replace the two directory placeholders with the printed artifact paths:

```powershell
python examples/compare_agent_strategies.py PROPOSAL_DIRECTORY TOOL_LOOP_DIRECTORY --output .keel/strategy-comparison.json
```

The offline exporter refuses to overwrite output. It retains unsuccessful and
environment-error records alongside successes, preserves task groups, and
rejects mismatched/missing tasks, shared settings or implementation hashes.
It summarizes saved harness outcomes without independently replaying Docker or
authenticating the artifacts. Reported remote model labels do not pin weights.
There are no automatic retries, significance claims or success-only means.
This previously debugged task is a diagnostic only. Generalization requires
additional frozen, previously untested real tasks; repeating this task does
not increase independent coverage.
