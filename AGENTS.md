# Repository development guidance

Before creating or changing experiment runners, environment setup, indexing,
external-tool adapters, progress reporting or resume behavior, read
[the experiment engineering runbook](docs/development/experiment-runbook.md).
Use its shared implementations and relevant regression tests instead of copying
the failure-prone patterns described there.

- Every long stage needs observable progress and an enforced time budget.
- Expensive completed work must be reusable after input/configuration checks;
  preserve prior runs and record implementation migrations explicitly.
- Keep telemetry failures distinct from required checkpoint/result failures.
- Do not repair reference labels, replace failed tasks, or treat unavailable
  engines as zero-quality results to make an experiment appear successful.
- After a new failure class is understood, update the runbook with evidence,
  a general prevention rule, reusable code and an appropriate regression check.
  Separate verified facts from suspected causes and untested fixes.

These instructions do not grant additional permissions or authorize changing
external applications. They do not imply that every existing script already
implements the runbook or that Keel automatically retrieves it at runtime.

## Ongoing project learning journal

The user requests a persistent record of observations and decision lessons for
development and interview preparation. Use
[the learning journal](docs/development/learning-journal.md) as the shared entry.
At each project turn, read relevant entries and update this same document with
new observations, corrections, decisions, failed attempts, validation or limits.
Extend an existing case rather than duplicating it. For explanation-only turns,
briefly record the clarified judgment or add a no-new-evidence index entry; do not
invent progress or repeat long passages. Keep evidence links and distinguish
planned work, developer changes, model actions, local checks and real evaluation.
Preserve prior failures/costs and mark superseded conclusions explicitly. Never
store credentials or claim that documentation itself is runtime learning.
