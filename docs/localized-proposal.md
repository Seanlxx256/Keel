# Optional autonomous-localization proposal path

Status: offline-tested prototype. No live-model success or comparative gain.

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

1. Scout builds a Python source structure from file names and AST class/function
   names and line numbers. Protected write targets are excluded. Reads use the
   ordinary Workspace permissions, read size cap, budget, cache and telemetry.
2. One model request selects 1..8 existing files and 1..8 literal query anchors.
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

The initial structure builder scans all writable Python sources and fails if
the cumulative structure or final request exceeds the context cap. It also
consumes tool calls per file and can exhaust the global budget before inference.
It does not silently omit later files. This is deliberately bounded but not yet
scalable for arbitrary repositories. No hierarchical map paging/graph ranking,
multi-stage function localization or candidate reranking is implemented.

File reads are still limited to 1 MB. Selected windows may exceed the unchanged
proposal request cap and must fail rather than silently remove evidence. Python
syntax unsupported by the current parser yields no symbols for that file. The
model can still choose poorly; offline tests do not measure localization quality.

Do not launch another paid HTTPX run yet. First measure map and selected-context
size offline on base-only snapshots, then freeze a bounded comparison protocol.
Changing a default mode, replacing the current index or widening execution
permissions would be an architectural change requiring explicit discussion.

The first [offline capacity measurement](evaluations/localization-capacity.md)
has now completed: HTTPX and Starlette overflowed the 12KB structure cap before
inference, while Flask-WTF's first request fit. No selected-source repair context
or live-model quality was measured. Hierarchical file-first selection is needed
before applying the prototype to HTTPX; increasing limits is not the default fix.

## Validation

Three new tests cover autonomous scope selection through exact editing and real
local acceptance, wrong/missing/protected scope and unmatched anchors, rejection
of operator localization, and pre-model context overflow. Together with proposal
(13), Agent (26) and native/LangGraph orchestration (13) tests: 55 tests passed.
These are component/integration checks, not real-model repair results.
