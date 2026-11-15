# Controller-executed fixed acceptance

This opt-in broker runs a server-defined JUnit-producing acceptance contract using
the existing Docker `CommandRunner` and `Workspace.verify`. It is not a general
shell/MCP executor or a new SWE-bench grader.

## Configuration

Retain the existing `read_broker` repository binding, then add:

```json
{
  "execution_broker": {
    "tasks": {
      "task-a": {
        "execution": {
          "backend": "docker",
          "image": "sha256:REPLACE_WITH_64_HEX_IMAGE_ID",
          "cpus": 1,
          "memory_mb": 1024,
          "pids_limit": 128
        },
        "acceptance": [{
          "command": ["python", "-m", "pytest", "tests/test_parser.py", "--junitxml={junit}"],
          "junit": true
        }],
        "max_seconds": 120
      }
    }
  }
}
```

Grant `"verifier": ["verify"]` in the principal's `tools`. Optional
`require_execution_broker: true` rejects worker-reported verification events as
a substitute for this execution path. Existing task acceptance must normalize to
the exact server contract. Workers cannot supply different commands, images,
resource settings or roots. This first broker requires an immutable Docker image
identity and JUnit-enabled commands. Non-JUnit verifier protocols, including some
official-harness wrappers, need a separate adapter rather than being silently
treated as equivalent.

## Actual execution and result transfer

Runtime `Workspace.verify` automatically routes to the advertised capability.
It sends source snapshot and acceptance hashes plus remaining time. The controller
persists an intent and starts a single bounded executor thread; the HTTP request
returns a job ID promptly. Worker polling uses separate short requests.

The executor checks source identity, records Docker health, acquires compliant
write-path locks, and executes fixed commands with the shared read-only/no-network
Docker runner. Source hashes are checked again after execution. JUnit metadata,
stdout/stderr, normal ledger/trace and heartbeat are preserved per job. Assertion
failures with usable test evidence remain test failures; Docker unavailability,
timeouts and incomplete test evidence produce unavailable results.

Large result JSON is preserved intact and transferred in 64 KiB byte pages. Worker
checks exact artifact length/SHA-256, authority and source/contract fingerprints
before importing test evidence. Output is not silently shortened to fit a single
control response. Snapshot coverage is the existing Workspace file policy, not
every byte on the host filesystem.

## Loss and recovery

Same operation ID/input returns the original job ID without executing again.
Another outstanding start in the same run is denied. After controller restart,
unfinished jobs become unknown unless the current instance actually owns their
executor; they are never automatically relaunched. Latest job ID is retained in
the client's optional durable checkpoint.

Recovered sessions can query `verification_status(job_id)` and
`verification_page(job_id, offset)` after reconciling any pending RPC. They cannot
start a new acceptance job. An unavailable result is not a zero repair score or a
reason to change business code blindly.

## Boundaries and validation

The server cap is explicit (up to 600 seconds), clamped by worker remaining time.
Source enumeration and filesystem I/O use cooperative checks. A blocked OS read is
not forcibly interrupted. One executor slot is available per controller instance;
this is not a cluster scheduler. No SQLite transaction is held during Docker work.

Execution still uses a daemon thread. Bounded graceful shutdown and recorded,
identity-checked container reconciliation are now implemented; see
[shutdown and orphan inspection](controller-execution-cleanup.md).
Forced controller termination can still leave a job unknown and Docker cleanup
unconfirmed. Reconciliation is explicit and does not certify all daemon resources.
An explicitly new authorized run may be a new attempt; this interface does not
globally deduplicate all evaluations of identical source.

Execution is controller-observed; test adequacy, candidate integrity and official
benchmark grading remain separate checks. The full repository is mounted using
the existing runner policy: do not keep unrelated secrets inside task sources.
Arbitrary host access/egress and malicious external source writers remain outside
the broker's enforcement guarantee.

Seven protocol fixture tests in `tests/test_execution_broker.py` passed. Actual
Docker acceptance, real providers and production performance remain unvalidated.


Current evidence and remaining boundaries: [2026-11-15 validation](development/governance-validation-20261115.md).
