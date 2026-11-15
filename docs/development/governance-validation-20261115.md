# Governance validation, 2026-11-15

The deferred non-Docker checks have now been run. This supersedes earlier
implementation-time statements that only syntax had been checked. It does not
supersede the boundaries on Docker, provider billing or distributed deployment.

## Results and preserved evidence

| Run | Result | Evidence |
|---|---|---|
| Initial new fixtures, harness Python | 92 attempted: 82 passed, 1 failed, 9 dependency skips | `.keel/governance-regression-20261115/run-a67283e20f0c` |
| New fixtures, existing SDK environment | 92 passed, no skips | `.keel/governance-regression-20261115/run-ba476b61a6e1` |
| Existing compatibility suite | 118 attempted: 117 passed, 1 error | `.keel/governance-regression-20261115/compat-21b3d7de34e5` |
| HTTP plus official SDK memory integration | 2 passed | `.keel/governance-regression-20261115/sdk-2037810ae1a3` |
| Final new fixtures plus integration | 95 passed, no skips, 21.130s test time | `.keel/governance-regression-20261115/final-59d6f224a24c` |

Each test-run directory preserves its original `console.log` and `report.json`,
including interpreter/command, elapsed time and source hashes. Earlier failures
are retained, not rewritten as passes. Repeated runs are not independent tasks or
additional quality successes. No paid model or actual Docker command was dispatched.

## Corrected test defect

The initial failing assertion assumed LF after `Path.write_text`, which emits
CRLF on this Windows host. The broker correctly preserved the actual UTF-8 bytes
and their hash. The test now compares decoded source bytes, and an additional
explicit UTF-8/CRLF fixture checks preservation and SHA-256 on all platforms.
Production read behavior and source-hash checks were not weakened.

Nine initial MCP skips reflected a missing optional `jsonschema` dependency in
the harness interpreter. An already-installed Python 3.11 environment at
`D:/code/monocular_depth_estimation/.venv/Scripts/python.exe` supplied it and the
official MCP SDK. No download, environment installation or fake validator was used.

## Confirmed environment blocker

`tests.test_mcp_client.McpClientTests.test_real_compass_stdio_schema_errors_and_shutdown`
still errors with `PermissionError`. The independent diagnostic at
`.keel/governance-regression-20261115/stdio-diagnostic-7558667b021d/console.log`
reproduces `WinError 5` in plain `asyncio.create_subprocess_exec` before Keel or
MCP is loaded. The stack reaches the Windows asynchronous pipe `CreateFile` call.

This establishes a limitation of this execution context's asynchronous subprocess
pipe access. It does not establish a Keel regression, WSL disk failure, or that the
operator's ordinary terminal has the same restriction. No OS permissions were
changed and the failed test was not turned into a skip. Ordinary Compass stdio
protocol roundtrip through a regular subprocess passed in the compatibility suite;
that is a different transport path from the blocked official-SDK asyncio pipe.

## Additional integration coverage

`tests/test_mcp_broker_sdk.py` adds two actual loopback HTTP integrations using the
official MCP SDK's memory transport:

1. Authentication, advertised tool policy, SDK invocation callbacks, full artifact
   paging, source checks and worker-local role-owned evidence import.
2. Out-of-band HTTP cancellation while the original invocation is pending, followed
   by preservation of its original operation ID and unknown effect record.

These are real controller HTTP and SDK protocol calls against an in-memory fixture,
not a deployed Serena service, a subprocess MCP server, or proof of OS isolation.

## Still not validated

- Actual Docker execution, container ownership/removal and daemon cleanup.
- Official-SDK stdio on this restricted host, real subprocess descendants and crashes.
- Real provider requests, lost-response accounting and authoritative billing.
- Queue-to-Docker task execution and all proxy endpoints under production concurrency.
- Cross-node orchestration, network/credential bypass resistance and service SLAs.

This is focused regression coverage, not the full repository CI suite, an official
SWE-bench repair result or a production readiness certification.

## Follow-up: stage-aware transport handling

The typed diagnosis now reaches local and controller-routed agent observations.
The final follow-up group passed 89 tests without skips, including eight new stage
contracts and the added HTTP typed-failure integration. Existing MCP-client checks
remain 9 passed/1 environment error; the original stdio test is not skipped or
relabelled successful. Preserved details are in
[MCP transport failures](../mcp-transport-failures.md).

## Consolidated frozen baseline

`.keel/governance-regression-20261115/unified-v1` preserves a declared 27-module
plan, implementation/test byte hashes, `source-snapshot.zip`, its SHA-256 receipt,
the original console and watchdog. The suite attempted 249 tests in 90.182s:
248 passed, one error, zero assertion failures and zero skips. The error remains
the known official-SDK async stdio PermissionError, now reported as typed
`McpTransportUnavailable`; it is not a newly discovered repair regression.

The ad hoc child runner then failed to write its report because it did not create
the `results` directory. The shared watchdog deliberately leaves child output
creation to the child. Preserve this publication failure: `assessment.json` was
subsequently extracted from the original unittest log, not from a rerun, and is
not a replacement successful child receipt. It binds console/archive/watchdog
hashes and confirms implementation plus declared test/runner bytes remained
unchanged. No completed tests were repeated to repair this metadata error.

The frozen archive is a reproducible diagnostic baseline, not an approved release,
Git commit, full CI pass or validated deployment. No Docker or paid model call
was dispatched. Existing narrower runs overlap and must not be added together as
independent coverage or task successes.

## Ordinary-shell targeted confirmation

User-provided console evidence reports all 10 `tests.test_mcp_client` tests
passing in 4.337s under the same SDK interpreter in ordinary PowerShell. The
previously blocked real Compass stdio/schema/shutdown test passed. Together with
the preserved ordinary-shell pipe controls, this establishes availability in that
context, while the restricted agent context still has its recorded failure.
The targeted run was not independently captured by the developer; no new merged
suite, full CI, Docker or deployment pass is inferred.
