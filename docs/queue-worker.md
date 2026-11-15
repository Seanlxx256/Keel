# Supervised queue worker

`python -m keel.queue_worker --plan worker-plan.json` runs **one** queued task,
then exits. It does not poll forever, silently resume a task, or retry a paid call.
The CLI itself is the supervisor; actual `keel.runtime.run` executes in a child
process. Docker acceptance is required and there is no local-backend fallback.

## Trusted plan and queue payload

An operator supplies a protected plan outside the untrusted repository:

```json
{
  "remote": {
    "endpoint": "http://127.0.0.1:8788",
    "token_env": "KEEL_WORKER_CONTROL_TOKEN",
    "task_id": "task-a"
  },
  "task_path": "D:/KeelControl/tasks/task-a.json",
  "task_sha256": "REPLACE_WITH_SHA256_OF_EXACT_TASK_FILE_BYTES",
  "repo": "D:/TaskWorkspaces/task-a",
  "output": "D:/KeelControl/attempts/task-a-1",
  "state_root": "D:/KeelControl/worker-locks",
  "max_seconds": 600,
  "allow_env": ["KEEL_MODEL_API_KEY"]
}
```

The task file is a normal complete Keel configuration with explicit Docker
execution and budget. Omit its governance field: the worker supplies authenticated
remote governance and a separate runtime checkpoint. Explicit diagnostic execution,
if configured, must also use Docker. Model/tool credentials are inherited only by
explicit environment-name allowlist, plus the worker's own governance credential.
The child is a trusted Runtime host, not untrusted code placed in a sandbox.

The queue item payload must contain exactly:

```json
{"task_config_sha256": "REPLACE_WITH_THE_SAME_TASK_FILE_SHA256"}
```

Queue data cannot choose a command, executable, configuration file or repository
path. Hash mismatch, unknown payload fields and local execution are rejected before
Runtime dispatch. Do not put secrets in the plan or task file.

## Lifecycle

1. Validate task identity and paths; exclusively create attempt output and acquire
   a workspace lock in the protected state root.
2. Begin a supervisor control session; claim and start a task with its current
   fencing number. Historical RPC responses cannot trigger dispatch.
3. Write an effective configuration receipt. Runtime time is clamped to the
   supervisor's remaining work budget; the final ten seconds are reserved for
   local cleanup and control finalization.
4. Launch a trusted child Runtime process. The parent emits progress, watches
   process exit and explicitly renews the task lease every 30 seconds.
5. On timeout, controller outage or renewal failure, stop the child containment
   and retain uncertain task state. There is no automatic requeue.
6. On normal exit, check result status against exit code, hash `result.json`,
   attempt local process cleanup, and submit a worker report to the queue.

The supervisor and child have separate governance run IDs and checkpoint files.
They consume the same server-configured principal/scope quota. The queue remains
bound to the supervisor run; actual model/tool activity belongs to the child run.

## Evidence and limitations

`supervisor.json`, `supervisor-progress.jsonl`, `runtime-console.log`, effective
`runtime-input.json` and Runtime's normal result/trace/ledger/patch are preserved.
Existing outputs are rejected, never overwritten. Use a fresh output for a new
attempt. `reported_passed` remains worker-reported acceptance, not a controller
independent certification or an official SWE-bench grade.

Windows uses the existing Job Object bootstrap before Runtime starts; POSIX uses
a dedicated process group and the shared bounded cleanup helper. Cleanup records
do not certify all descendants or Docker-daemon containers have disappeared.
Escaped/reparented processes and a malicious same-user trusted host remain outside
this monitor's guarantee. This is lifecycle observation, not kernel/network audit.

All workers touching the same repository must share `state_root`. A crash can
leave a stale lock, intentionally blocking another attempt until an operator
inspects outstanding processes and effects. The lock is single-host coordination,
not a cross-node lease. A workspace should be dedicated to one task attempt.

The supervisor does not create isolated git worktrees, download repositories,
prepare Docker images or grant new tool permissions. Existing trusted task setup
and permission policies still apply. Model/API and MCP calls may use the controller brokers; mandatory deployment
egress enforcement remains separate work.

Six contracts in `tests/test_queue_worker.py` passed in focused validation.
They do not establish live queue-to-Docker execution or real provider behavior.


Current evidence and remaining boundaries: [2026-11-15 validation](development/governance-validation-20261115.md).
