# Controller-executed replacements

The write broker extends the read broker's server-owned repository catalog with an
explicit writable subset. It supports only exact text replacement, not arbitrary
commands, file deletion/creation, MCP calls or acceptance execution.

## Configuration

In an existing `read_broker.repositories` task entry add `writable_files`:

```json
{
  "root": "D:/TaskWorkspaces/task-a",
  "files": ["src/parser.py", "tests/test_parser.py"],
  "writable_files": ["src/parser.py"]
}
```

The subset must be readable ordinary files and pass existing protected-path checks.
Tests and internal metadata cannot be made writable through this setting. Grant
`replace` in the principal's `tools.implementer` list. Optionally set
`require_write_broker: true` to deny legacy `tool_started` replacement authorization.
Changing the write catalog changes run policy identity and requires a new run.

The begin response advertises write capability. Both tool-style and proposal-style
calls through `Workspace.replace` then use the controller. ToolGateway retains its
work-item `allowed_files` check; server catalog provides a separate task boundary.
The server does not independently reconstruct the Planner's work-item scope.

## Before and after each effect

The worker sends the source's raw SHA-256 plus exact `old`/`new` strings. The server
checks task authorization, writable path, source version and a single matching
occurrence. It persists the expected before/after hashes and write intent before
invoking the shared `Workspace.replace` implementation. Existing Python AST and
static edit audit checks run before the effect. The source hash is checked again
immediately before the write.

The resulting file is hashed and the outcome/cache committed. A completed duplicate
returns a historical receipt without writing again. Worker receipt import requires
the predicted target hash and actual worker workspace bytes to match the controller.
This first version requires shared source storage; it does not synchronize a second
workspace or apply the same patch independently on both sides.

## Uncertain effects

A write attempt followed by an error or controller crash stays `inflight`/unknown.
The same operation is never automatically replayed. A durable unique pending-path
guard rejects new writes to that path, including from another controller instance
sharing the same local DB. Reads remain available for investigation.

`session.inspect_pending_write()` queries the persisted write record while retaining
the original pending operation. It returns recorded hashes/status, not permission
to retry, and does not certify current file contents. A recovered session can use
this read-only query. A normal session with no pending operation can call
`write_status(operation_id)`.

There is deliberately no automatic unlock, rollback or requeue. Use the trusted
local operator workflow below; never edit SQLite rows merely to unblock a task.

## Trusted operator resolution

First stop and inspect the original worker and its outstanding effects. All
controller writers must run the updated file-lock protocol; stop old-version
writers before using this workflow. The CLI is controller-local administration,
not a worker RPC or automatic repair action.

Create a fresh observation plan (replace identifiers with the actual saved ones):

```powershell
python -m examples.resolve_controller_write --config service.json --output write-plan.json preview --principal worker-a --run-id ORIGINAL_RUN_ID --operation-id ORIGINAL_WRITE_OPERATION_ID
```

The plan binds original request identity, before/after hashes and currently
observed file hash. It does not choose a decision or certify original causality.
After inspection, explicitly declare one of:

- `applied`: current bytes exactly match the intended target.
- `no_effect`: current bytes exactly match the recorded source.

```powershell
python -m examples.resolve_controller_write --config service.json --output write-resolution.json resolve --plan write-plan.json --decision applied --operator operator-name --reason "Stopped original worker and inspected source plus execution records" --quiesced
```

The operator name and quiescence acknowledgement are trusted local assertions,
not independently authenticated forensic findings. Cross-process advisory locks
exclude compliant active writers while checking and committing the decision.
The same lock is now used for normal controller replacement. Never delete these
small lock files: OS lock ownership disappears on process exit, while unlinking
an in-use lock inode could split the coordination boundary.

Resolution checks that the plan is still current and the selected decision matches
the actual hash. A partial/unexpected file or stale plan remains blocked. This
command does not repair partial files; prepare a separate authorized intervention
and fresh observation if needed.

In one transaction, resolution records the operator/reason, closes the original
run as failed, retains unknown model usage, stores a terminal rejection for the
old write RPC, and releases the pending-path exclusion. Even an `applied` decision
does **not** let the old worker continue: it must use a new authorized attempt.
The result is operator adjudication, never independent acceptance.

An exact repeat of the same plan/decision/operator/reason returns a historical
receipt; conflicting decisions are rejected. Always use a fresh output filename.
The plan and receipt are preserved; all source bytes remain unchanged by this CLI.

## Limits

Source/result files remain at most 1 MB and requests within the existing control
transport bound. File I/O uses cooperative budgeting, not forced OS cancellation.
The existing write is an in-place filesystem operation: partial writes are possible
on disk failure, which is why attempted effects remain uncertain. Hash comparison
is optimistic coordination, not an OS-level compare-and-swap against malicious
external writers or a guarantee against filesystem TOCTOU races.

Protect shared source storage and controller credentials. The RPC-only requirement
cannot prevent a compromised same-user host from writing directly. Full sandbox,
network and credential enforcement remain deployment work. A successful replacement
receipt is not successful acceptance or independent grading.

Nine fixture contracts in `tests/test_write_broker.py` passed. No actual Docker,
provider or filesystem crash-durability certification is claimed.

Eight further contracts in `tests/test_write_resolution.py` cover adjudication,
stale/conflicting evidence, active locks, old-run revocation and worker-RPC denial.
These eight contracts passed on Windows. Live competing-process stress and
other operating systems remain unvalidated.


Current evidence and remaining boundaries: [2026-11-15 validation](development/governance-validation-20261115.md).
