# Controller-executed read tools

The read broker executes approved repository observations on the controller.
It reuses `Workspace` path checks, file observations and literal search, then
imports controller evidence through the existing Runtime `ToolGateway`.
It does not execute arbitrary shell commands, MCP adapters, edits or acceptance.

## Configure the controller

Add this fragment to the existing service config, retaining path/scopes/principals:

```json
{
  "read_broker": {
    "evidence_root": "D:/KeelControl/read-evidence",
    "repositories": {
      "task-a": {
        "root": "D:/TaskWorkspaces/task-a",
        "files": ["src/parser.py", "tests/test_parser.py"]
      }
    }
  }
}
```

The repository is selected by authenticated principal task binding, never a
client-supplied root. Files are a server-owned explicit readable catalog. Reading
tests does not grant permission to edit tests. The controller database and evidence
directory must stay outside each repository.

Grant the desired tools per role in that principal's existing `tools` mapping:
`list_files`, `read_file`, `read_page`, `read_lines`, `search_code`. An optional
`"require_read_broker": true` denies legacy `tool_started` authorization for those
reads. Other role tools keep their existing policy. Internal repository metadata,
path escapes, file aliases and hard-linked/nonregular files are rejected.

## Runtime routing and evidence

The begin response advertises broker capability and catalog policy hash. The
existing ToolGateway automatically routes supported reads through `tool_read`.
No new worker task switch is required. The service checks identity, role and tool
grant, publishes an intent, performs I/O outside the control DB transaction, and
commits the response plus a controller-owned outcome event.

Controller artifacts contain a per-run read ledger/trace. Every returned
observation has a controller fact ID, operation ID, authority label and raw source
SHA-256 values. The worker verifies those hashes against its workspace **before**
importing evidence into its local ledger. Local fact IDs and controller fact IDs
are kept distinct; normal role visibility and handoff rules still apply.

A cached duplicate is labelled historical. It is not automatically fresh source
evidence: worker hash verification still applies. Unknown interrupted operations
are not silently re-executed. Recovered clients may reconcile the saved RPC but
cannot initiate new reads.

## Bounds and changed read behavior

This first broker supports 1..128 explicitly listed files, at most 1 MB each and
8 MB total. It serializes file observations and uses a five-second cooperative
work budget with checks between operations. This does not forcibly interrupt a
blocked OS filesystem call; local filesystem availability remains a deployment
requirement. No network mount or adversarial filesystem timing guarantee is made.

`read_file` returns the first source page with `next_line`; it does not transfer
an entire large file. `read_page`/`read_lines` return at most 80 lines and 3,000
characters. An oversized single line fails explicitly. Continue with `next_line`;
local recall retrieves only the imported page, not unseen controller file content.
Literal search retains the existing match cap and truncation metadata.

Catalog policy changes invalidate old run bindings. Ordinary source edits do not
change policy, but are detected by observation and worker source-hash checks.
The controller and worker must access matching source versions. The broker does
not synchronize workspaces or propagate patches across machines.

## Boundaries and validation

This creates an authoritative record that a controller file observation occurred;
it does not prove the resulting diagnosis or patch is correct. The legacy-intent
restriction is an RPC policy, not an OS prohibition on a modified worker reading
files directly. Non-ToolGateway host paths retain their own behavior. Mandatory
routing still requires a trusted host, protected source/catalog and deployment
credential/filesystem/network isolation. The shared path checker plus hash
comparisons do not certify absence of adversarial filesystem TOCTOU races.

Exact replacements now have a separate [write broker](controller-write-broker.md).
Controller MCP navigation and fixed Docker acceptance now have separate brokers.
Ten contracts in `tests/test_tool_broker.py` passed, including explicit UTF-8/CRLF
preservation. Real Docker and provider behavior remain unvalidated.


Current evidence and remaining boundaries: [2026-11-15 validation](development/governance-validation-20261115.md).
