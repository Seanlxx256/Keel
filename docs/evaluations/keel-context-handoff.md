# W8 role-boundary context handoff

Agent tasks accept top-level boolean `context_handoff` (default false).
When enabled, Planner receives up to four selected Scout file-read references
for the impact file list. Each Implementer receives up to four initial
Scout/Planner file-read references restricted to its declared file list.

Selection uses canonical relative paths, one fact per path, newest facts within
a source, and Planner-before-Scout preference. Byte hashes must match at selection;
changed and deleted source files are skipped. Generic search/list/MCP payloads,
model decisions and failed attempts are not auto-transferred. Each recipient gets
its own copied fact IDs and bounded previews. Full histories remain private.
The provided original fact IDs are provenance, not grants to recall those facts.

The matching check is not an OS lock or a guarantee against edits after selection.
Inherited evidence remains historical. Implementer sessions from earlier work items
are not shared; initial evidence is checked again for every work item. Transfers
are included in ordinary model-input token preflight. Inherited evidence no longer satisfies the optional require_evidence gate;
a local observation is required after the live failure documented below. Independent verification and
write protections are unchanged. The run result records handed_off_facts and
JSONL records selection plus source/recipient provenance.

Validation on 2026-10-15:

- 18 agent tests passed, including a full scripted model run proving opt-in
  Scout-to-Planner-to-Implementer handoff, exclusion of unrelated file contents,
  recipient IDs, fresh histories, and omission of source changed by an earlier item.
- Six memory tests passed, including four-fact bounds, per-file uniqueness,
  rejection of stale/deleted reads, host grants, isolation and cache invalidation.
- Existing default-off isolation behavior passed unchanged.
- Script CLI help and diff whitespace checks passed.

Live validation command (separate from the already passed no-handoff CPU/Docker
smoke result):

```powershell
python examples/run_keel_agent.py --backend docker --cpu --context-handoff
```

No live handoff performance or model-token savings are claimed from scripted
checks. W8 performance measurements on larger workloads remain outstanding.

Full regression: 212 tests, 207 passed, 5 optional-dependency skips, no failures. Compilation checks also passed.


Live handoff attempt `.keel/agent-smoke/beaaad22bd7a4e3a8f631fdd982fc543`
failed independent Docker verification in 120.437 seconds / six calls. Two facts
were handed off successfully; Implementer returned a claimed update without
calling a tool or editing. The inherited fact had incorrectly satisfied the local
observation gate. Gateway now tracks observed facts separately from visible
(granted) facts; grants permit recall but do not unlock early completion. A new
scripted regression reproduces the false final, rejects it, then succeeds after
an actual read and replacement. This still does not prove edits from a summary;
independent acceptance remains authoritative.
