# Keel sequential role lifecycle validation

On 2026-10-15, Keel gained an explicit role state machine around its existing
sequential runtime. This starts the W6–7 skeleton acceptance work while Compass
quality tuning remains deferred.

Normal execution follows Scout → Planner → Implementer → Verifier → Auditor →
finished. Failures enter Critic before a failed terminal outcome. Baseline test
metadata checks are a separate Verifier phase that returns to Scout; they cannot
substitute for final verification. Supplemental configured queries can return
an agent-generated plan to Scout before final plan validation. No automatic retry,
concurrent scheduling, or new model role was introduced.

Each role entry/exit is persisted in JSONL. `result.json` records ordered role
history, phase, completed/failed status, monotonic duration, and terminal outcome.
A failed acceptance command is recorded as a failed Verifier phase even when
the runtime subsequently audits its effects. Unexpected exceptions still propagate
while preserving a failed lifecycle artifact and Critic handoff.

The real explicit-mode demo at
`.keel/demo-runs/54b20f8870954d2493d051c37f8d0b53/` changed `API_VERSION` from 1 to 2,
passed an independent Python acceptance subprocess, passed scope/static audit,
and preserved patch, ledger and trace artifacts. Its role history contains all
five normal execution roles and terminates with `passed`. It used no model calls.
This is a controlled smoke task, not an autonomous coding benchmark.

Tests cover illegal role order, terminal-state rejection, baseline-phase handling,
verification failure and Critic handoff, and unexpected exception preservation.
The lifecycle remains local JSONL/JSON telemetry. OTel export, an external MCP
gateway, isolated concurrent workspaces, and richer Critic recovery remain separate
work; the new state machine alone does not complete W6–7.
