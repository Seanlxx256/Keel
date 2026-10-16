# Optional autonomous-localization proposal path

Status: offline-tested prototype, now file-first hierarchical localization.
No live-model success or comparative gain.

Design research inspected Agentless's
[localization module](https://github.com/OpenAutoCoder/Agentless/blob/main/agentless/fl/FL.py)
and [repair context construction](https://github.com/OpenAutoCoder/Agentless/blob/main/agentless/repair/repair.py)
on 2026-10-16. Those modules separate repository/file/location selection from
repair context and patch generation. The links track main, not a pinned version;
this records design provenance, not a reproducible external baseline. No upstream
code, prompts, dependencies or benchmark claims were imported.

## What was grafted

Select `mode: localized-proposal` in a normal Keel task configuration. Omit
operator `proposal` and `work_items` fields; both are rejected. Existing agent,
model, budget, execution and acceptance settings remain applicable.

1. Scout lists writable Python source paths, excluding protected targets, and
   asks the model to select 1..8 exact files. No source bodies are read yet.
2. Only selected files are read for AST class/function names and line numbers.
   A second model request chooses a subset of those files and 1..8 literal
   query anchors. Reads use ordinary permissions, size caps and accounting.
   Schema, exact fields, types, scope membership and at least one matching anchor
   per file are checked. No fuzzy path correction or guessed query replacement.
3. The host collects windows with the existing proposal evidence constructor.
   Planner records a single deterministic work item for that selected scope.
4. Implementer uses the existing one-call exact replacement proposal path. Batch
   validation happens before writes, followed by ordinary Verifier, Auditor and
   failure reporting. LangGraph/native lifecycle abstractions remain intact.

Source signatures alone are not patch evidence. Repair receives actual source
windows and hashes. Proposal text or a claimed success cannot skip validation.
Localization and repair share the same global budget; there is no hidden free
model call or automatic retry. Raw localization and model identity metadata are
recorded in the existing ledger/trace.

This is a new opt-in execution path, not a replacement for the six-role default.
It retains all lifecycle phases but uses deterministic planning instead of an
independent Planner model session. It must not be advertised as an equal-access
single-agent baseline or a full Agentless implementation.

## Limits before a live experiment

The first prototype scanned all writable Python source symbols and overflowed
on HTTPX/Starlette. It has been replaced within this optional mode by file-first
selection. Both requests independently enforce the unchanged context cap. A long
path list or selected symbol map still fails rather than silently omitting later
entries. No directory paging, graph ranking, fine-grained line localization or
candidate reranking is implemented. File path enumeration still incurs Workspace
snapshot hashing; fewer tool requests do not establish reduced physical I/O.

File reads are still limited to 1 MB. Selected windows may exceed the unchanged
proposal request cap and must fail rather than silently remove evidence. Python
syntax unsupported by the current parser yields no symbols for that file. The
model can still choose poorly; offline tests do not measure localization quality.

Do not launch another paid HTTPX run yet. First measure map and selected-context
size offline on base-only snapshots, then freeze a bounded comparison protocol.
Changing a default mode, replacing the current index or widening execution
permissions would be an architectural change requiring explicit discussion.

The [offline capacity measurements](evaluations/localization-capacity.md)
retain both versions: the full-map first request overflowed on HTTPX/Starlette;
the new file-path first requests fit all three base snapshots. No model-selected
symbol/repair context or live-model quality was measured. This does not establish
that the complete pipeline fits or repairs HTTPX.

## Validation

Five localization tests cover selection through exact editing and real local
acceptance, invalid scopes/anchors/fields, operator-hint rejection, cap overflow,
unselected large files omitted from the symbol read stage, scope nonexpansion and
shared model-call budget exhaustion. A measurement test verifies no-network
preflight. Together with proposal (13), Agent (26) and native/LangGraph
orchestration (13) tests: 58 tests passed.
These are component/integration checks, not real-model repair results.

Normal successful execution now has **three model requests**: file selection,
anchor selection and patch generation. Each consumes the same global budget.
The second stage may narrow but cannot expand the first stage's scope. This is
an explicit cost/behavior change in an opt-in mode, not an unchanged two-call
implementation. Default multirole and operator-localized proposal modes remain.
