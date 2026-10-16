# Bounded verification repair

Proposal and localized-proposal runs may opt into `verification_repair_attempts` (integer 0..3; default 0). Failed acceptance can trigger another exact replacement proposal using current source, bounded observed errors and existing selected dependency contracts. All attempts share the original model/tool/token/wall-clock budget, declared files and acceptance commands. No gold patch or task-specific replacement is supplied.

Before another proposal, compare the workspace against the initial snapshot, reject undeclared changes and run source/metadata audits. Final acceptance and the existing final audit/mutation path still decide success. Policy, audit, model and budget errors stop the run; this is not a general error retry mechanism. Each completed verification is retained in `verification_attempts`; failed verification evidence is stored in the ledger. Retry events are nested inside the verifier phase, not a new six-role orchestration cycle.

Evidence reads current declared files and includes the smallest enclosing definitions for the innermost two declared-source traceback frames per failed case, plus the file header. When eligible traceback frames exist, earlier localization windows and unrelated declared files are omitted with explicit metadata; otherwise previous selected positions are used. Only `/workspace/` traceback frames within the declared file scope are eligible. Source edits can shift earlier selection positions; traceback locations provide current anchors, but the collector does not perform full semantic relocalization or expand file permissions. The regular context cap remains enforced without silently truncating source windows. Structured case errors are bounded to 32 records and 500 characters per field; generic stdout/stderr fallback is bounded to 1000 characters each. Full verification remains in the saved report.

Prepare a fresh HTTPX development trial (no provider calls):

```powershell
python examples/run_transition_task.py --package .keel/task-packages/httpx-1588-v1 --model-config .keel/model-openai.json --output .keel/transition-trials/httpx-1588-repair-loop-v1 --strategy localized-proposal --baseline-feedback --require-change --dependency-module httpcore --select-contracts --max-context-bytes 24000 --repair-attempts 2
python examples/run_transition_task.py --output .keel/transition-trials/httpx-1588-repair-loop-v1 --execute
```

Normally four initial calls and at most two further repair calls are made; the shared original budget remains authoritative. This trial starts from the original base, not an earlier failed patch. Existing grids and failures are preserved. Offline tests establish recovery and budget enforcement on fixtures; they do not establish HTTPX acceptance or a benchmark improvement.

## Focused evidence correction

The first live repair-loop run stopped before its fifth model call: assembling all traceback callers and original selections required 28,353 bytes under a 24,000-byte cap. The focused collector above fixes this evidence assembly issue. Offline replay of that failed workspace produced a 10,342-byte request even with all compact dependency contracts (a superset of selected signatures). This is a capacity check, not a successful repair. Repair preparation/proposal failures are now attributed to implementer rather than verifier. Original artifacts remain unchanged.
