# Controller-owned durable task queue

The queue is an opt-in API for trusted worker hosts. Existing Runtime execution
does not automatically become a queue worker. It uses the controller's existing
single-host SQLite transaction boundary; this is not a Redis/Ray/Kubernetes queue.

## Why expiry cannot mean retry

A worker can perform an edit or paid model call and crash before reporting it.
Automatically putting its task back in the ready queue can duplicate that effect.
The implemented state transitions therefore are:

```text
queued -> claimed -> running -> reported_passed / reported_failed
             |          |
             +----------+---- lease expired -> unknown
unknown / reported_failed -> explicit operator decision -> queued (next fence)
```

Every claim increments a fencing number and binds the item to an authenticated
principal, configured task and run. Start, renewal and completion require that
exact binding and current lease. A stale worker cannot publish a new completion.
This fences queue state only: it cannot stop an already-running external process.

Worker-reported success is `reported_passed`, never independent acceptance.
Its artifact SHA-256 is a reference, not proof the artifact exists or passed tests.
Controller queue events are retained in `control_task_events`; ordinary governance
event inspection does not merge these tables automatically.

## Enqueue on the trusted controller

Use the existing control-service configuration and credentials. The payload is a
bounded JSON object; store large task/workspace artifacts elsewhere.

```powershell
python -m examples.manage_control_tasks --config service.json --principal worker-a --id task-item-1 enqueue --payload payload.json
python -m examples.manage_control_tasks --config service.json --principal worker-a --id task-item-1 status
```

The worker RPC API has no enqueue or requeue permission. A trusted operator can
explicitly requeue an uncertain/failed item after inspecting external effects:

```powershell
python -m examples.manage_control_tasks --config service.json --principal worker-a --id task-item-1 requeue --fence 1 --reason "Inspected original run and workspace; recorded safe retry decision"
```

The CLI records the reason; it cannot independently prove that the operator's
reason is correct. Never automate this command on every timeout.

## Worker protocol

```python
claim = session.claim_task()  # authenticated RemoteSession, active run
item = claim['task']
if item is not None and claim.get('dispatch_allowed') is True:
    started = session.start_task(item['id'], item['fence'])
    if started.get('dispatch_allowed') is True:
        # Invoke the existing bounded runtime here, using trusted task configuration.
        # Queue payload is data; do not execute arbitrary payload shell commands.
        # During long work, explicitly renew before the lease expires:
        session.renew_task(item['id'], item['fence'])
        # After actual execution, submit its real result artifact hash:
        # session.finish_task(item['id'], item['fence'], status='failed',
        #                     artifact_sha256=sha256_of_result_file)
```

Each task lease lasts at most 300 seconds and cannot exceed the governance run
deadline. There is no automatic heartbeat thread or lease extension. Renewal must
be scheduled by the trusted worker host and must stop when that host loses control
of the task. A longer task requires periodic renewal within its run budget.

Lost-response reconciliation reuses the exact RPC identity. Replayed claim/start
responses carry `dispatch_allowed: false` and `historical_response: true`, so they
cannot be interpreted as a new dispatch. Inspect via `session.task_status(id)`.
Recovered clients may inspect queue status, but cannot claim, start or renew work.

## Status and limits

Implementation includes queue schema, controller RPCs, client methods and trusted
administration CLI. Seven new contracts in `tests/test_task_queue.py` cover core
transitions and service replay. They passed in the focused validation below. Production concurrency and Docker
execution remain unvalidated. A single-attempt supervised Runtime worker is now
available; external supervision and cross-node persistence remain separate work.


Current evidence and remaining boundaries: [2026-11-15 validation](development/governance-validation-20261115.md).
