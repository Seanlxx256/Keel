# Writable localization choices and read-only diagnostic evidence

The extended-budget development attempt stopped after three selections containing
a protected test path, despite two specific host corrections. It used only 7 of
60 calls and 43,040 of 400,000 tokens, with no edit or intermediate verification.
This was repeated invalid selection, not exhausted global allowance.

The generic interface now distinguishes selection_purpose=writable_edit_targets
and read_only_evidence_paths. The latter comes from host-observed source paths
outside the current writable catalog, not arbitrary paths inferred from model
prose. It lists at most eight navigation paths with an explicit omission count;
it does not limit the separate read tools to those paths. Host selection errors
are also provided as a separate bounded field rather than only nested goal text.

File choices in both single requests and catalog pages now have output enum
constraints bound to their actual writable catalog/page. Page carry entries remain
restricted to previously validated selections. Nonpaged requests do not inherit
arbitrary previous_selection hints. Existing host membership/path/audit validation
remains authoritative: a JSON-object provider or scripted model can ignore schema,
so invalid selections are still rejected in full rather than silently filtered.
Tests remain readable evidence and are not granted write permission.

Larger schema constraints count toward existing request-cap checks. The shared
paging implementation visits every catalog page and retains its global budgets;
no source truncation, task-specific path override or automatic source selection is
introduced. Empty writable catalogs fail before a model request.

## Offline validation and cost

Four new contract tests cover single-request enums, unstructured-provider schema
delivery, read/write separation with explicit host feedback, and a model ignoring
the enum still failing closed without edits. Existing paging, recovery, proposal,
refinement and task-runner checks also pass: 79 checks, 77 passed, two optional
LangGraph checks skipped in the harness environment.

Read-only reconstruction used the actual archived goal, Scout summary, evidence
and repository from extended-v1. Its old first request exactly matches the trace:
33,213 bytes. The real catalog has 510 writable Python files. New constraints
require two scripted catalog requests, 46,782 and 20,198 bytes, each below the
unchanged 48,000-byte cap. Every catalog path is visited and each output enum
matches the displayed page/carry. These are request bytes, not billed token counts.
This is an explicit overhead: one valid selection may now require two requests.
There is no claim that a real model will comply or that total cost is lower.

Artifacts: `.keel/repair-review/writable-selection-contract-v1/capacity-v2.json`
and its replay.py record source/request provenance and execute no paid model calls.
Earlier capacity/provenance files reflect the initial wording and remain intact.
Any real follow-up must use a new frozen plan, preserve the failed attempt and
evaluate actual selection behavior before declaring this failure class resolved.

A fresh extended-v2 launcher is prepared under .keel/repair-exploration/extended-v2,
binding the changed implementation to the same mini/source/tool/extended limits.
It has not been executed. An additional eighteen checks in the configured virtual
environment passed, including actual LangGraph orchestration paths (scripted
model responses, not a real-mini repair result). Earlier extended-v1 stays intact.

The user subsequently ran extended-v2. It reached four edit/verification rounds,
but failed and still produced rejected out-of-catalog responses. Its final page
selection lost the previously retained repair target, then Implementer attempted
to edit that file outside the revised evidence scope. Thus host validation held,
while schema compliance and cross-page task focus remain unresolved. See the
[real outcome](evaluations/extended-budget-exploration-v2.md); do not interpret the
offline passing controls above as proof this failure class is eliminated.
