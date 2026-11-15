# Acceptance shutdown and known-container reconciliation

This adds lifecycle handling for the controller's fixed acceptance executor. It
does not stop every model/tool call or certify all resources on the Docker daemon.

## Normal completion and graceful service shutdown

Before a managed Docker launch, the tracked runner persists its generated name,
job ID, owner-instance ID, expected image, mount roots and random launch labels.
Labels are added to the actual `docker run` command. A persistence failure blocks
that launch. No provider credentials or container environment are included in the
inspection projection.

On normal job completion, recorded containers are checked before the controller
publishes a usable test result. Unconfirmed cleanup changes the job status to
`cleanup_unconfirmed`; any completed result artifact remains available to the
operator, but the worker does not receive a fresh acceptance claim.

The control-service CLI handles its normal deadline, SIGINT and SIGTERM by:

1. Rejecting new acceptance starts and marking the executor stopping.
2. Attempting cancellation of recorded, identity-matched containers.
3. Waiting within the shutdown budget for current-instance executor threads.
4. Checking containers again after thread exit to catch late-launch races.
5. Writing `<ready-file>.execution-shutdown.json`.

The default cleanup budget is ten seconds plus required bounded storage work.
The CLI now stops both acceptance and MCP admission first and shares this budget
between them; the same receipt filename contains schema-version-2 component
results. See [MCP lifecycle](controller-mcp-lifecycle.md) for its narrower scope.
Live threads, inaccessible Docker, mismatched identities or exhausted inspection
budget remain `cleanup_unconfirmed`; the CLI exits nonzero for that state.
Embedding applications must explicitly call `service.close(timeout=...)`.

An earlier 'container absent' observation while a launch thread remains alive is
not sufficient for a stopped result. Shutdown receipts count older-owner records
separately; they are not silently certified by current-instance shutdown.

## Identity checks before removal

Inspection uses only a recorded name. It checks stored labels, immutable image and
expected repository/report mounts. If matched, deletion uses the inspected full
container ID, then checks that ID's absence through a successful Docker query.
Name reuse does not authorize deletion of an unrelated container.

Missing-container errors are distinguished from an unavailable engine through a
successful listing query. Unavailable Docker cannot prove absence. There is no
`prune`, wildcard removal, name-prefix sweep or local-execution fallback.

The tracked runner uses the same identity-aware cleanup for timeout handling;
ordinary untracked CommandRunner callers retain their prior cleanup behavior.
The label registry is trusted controller data, not protection against an attacker
with control of Docker metadata or the host database.

## After a crash or forced termination

Forced termination may bypass signal handlers and leave an unknown job/container.
Stop and inspect the original controller and worker first. Use the original
matching service policy/configuration to inspect only that job:

```powershell
python -m examples.inspect_execution_cleanup --config service.json --principal worker-a --run-id ORIGINAL_RUN_ID --job-id ORIGINAL_JOB_ID --output cleanup-observation.json
```

To remove identity-matched recorded containers after operator inspection:

```powershell
python -m examples.inspect_execution_cleanup --config service.json --principal worker-a --run-id ORIGINAL_RUN_ID --job-id ORIGINAL_JOB_ID --output cleanup-removal.json --remove --quiesced --max-seconds 10
```

Both outputs must be fresh filenames. `--quiesced` is a trusted operator assertion,
not automatic evidence the previous process died. Container observations and the
operator action are persisted; this command neither reruns tests nor changes a
previous test score. `no_recorded_launches` covers only the managed launch registry,
not proof the whole daemon is empty.

## Validation boundary

Seven fixture contracts in `tests/test_container_receipts.py` passed. They cover identity mismatch, ID-based removal,
daemon failure, prelaunch records, stopped dispatch and live-thread shutdown.
These use Docker CLI fixtures; actual orphan cleanup, Docker isolation and
cross-process shutdown remain unvalidated.


Current evidence and remaining boundaries: [2026-11-15 validation](development/governance-validation-20261115.md).
