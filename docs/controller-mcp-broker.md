# Controller-owned navigation MCP calls

This opt-in path runs explicitly configured navigation MCP tools on the controller
through the existing `McpTools`/official SDK boundary. Worker model text cannot
select executable commands, server URLs, environment mappings or arbitrary tools.
It is not a sandbox for untrusted MCP server programs.

## Server configuration

Retain the service's repository binding under `read_broker`. Add a task mapping:

```json
{
  "mcp_broker": {
    "tasks": {
      "task-a": {
        "servers": {
          "nav": {
            "command": "REPLACE_WITH_TRUSTED_MCP_EXECUTABLE",
            "args": ["REPLACE_WITH_OPERATOR_SERVER_ARGUMENTS"],
            "timeout": 15,
            "tools": {
              "find_symbol": {
                "roles": ["scout", "planner"],
                "description": "Find code symbols by their name; name is a string.",
                "read_only": true,
                "input_schema": {
                  "type": "object",
                  "properties": {"name": {"type": "string"}},
                  "required": ["name"],
                  "additionalProperties": false
                }
              }
            }
          }
        },
        "path_arguments": {"mcp__nav__find_symbol": []}
      }
    }
  }
}
```

This is a template, not a promise that a particular server exposes exactly this
tool/schema. Discover and verify its actual contract first. Existing stdio and
streamable-HTTP server specifications are supported; use environment references
for credentials. Install the repository's MCP optional dependencies on the
controller. No dependency download or server launch occurs merely by this example.

Grant the exact alias in principal `tools.scout`/`tools.planner`, matching policy
roles. Optional `require_mcp_broker: true` denies legacy direct MCP intent RPCs and
requires removing worker-local MCP server configs. The controller advertises only
granted descriptions, roles and schemas, not launch commands or credential settings.

Every alias must declare `path_arguments`, even `[]` for a name-only query. Declared
top-level file fields must name exact approved readable files. This initial mapping
does not support nested file arguments, directory grants or automatic discovery of
hidden path semantics. Operator/server schemas are both checked. Tool policy and
task identity are bound to the run; changing them requires a new authorized run.

## Runtime and evidence

Runtime wraps its MCP catalog with `RoutedMcpTools`; controller aliases are visible
to the same agent tool loop. Duplicate local/remote aliases are rejected. Actual
calls charge worker tool budget and use the remote control session. Server code
reuses `McpTools`, request lifecycle cleanup and schema validation.

The controller persists an operation intent, checks matching source fingerprint,
records dispatch immediately before `call_tool`, and observes whether a result was
returned. Eligible write paths are locked against compliant controller replacements
for the call; source snapshots are compared afterward. Confirmed source mutation
or missing result leaves the invocation unknown, with no automatic replay/rollback.
Known preparation/schema failures can be corrected without claiming execution.

Successful full output is saved as a hash-bound artifact and transferred in 64 KiB
pages using the shared remote artifact collector. No single-response truncation is
used. Latest operation identity can be retained in the optional client checkpoint;
recovered sessions may fetch existing result pages but cannot start a fresh call.

Worker verifies source identity again before existing ToolGateway imports the
observation as role-owned symbol evidence. The authority label deliberately says
**controller invocation with untrusted server output**: it proves a controlled call
was recorded, not that every returned code claim is true or relevant.

## Security and execution limits

`read_only: true` is an operator-reviewed declaration, not OS-enforced permission.
Source-diff checks cover the existing Workspace snapshot policy; they do not prove
absence of external network, filesystem or service side effects, nor prove which
repository the server actually used internally. Configure trusted adapters and
protect their environment. Do not use this path for arbitrary code execution.

Server request timeout is explicitly at most 20 seconds with bounded HTTP response
headroom. The SDK's process/async-context cleanup is reused; bounded owned-request
cancellation and managed shutdown are now implemented in the
[MCP lifecycle path](controller-mcp-lifecycle.md). Orphan descendants, older-instance
effects and remote server execution remain outside that guarantee. Snapshot checks are cooperative and
cannot forcibly cancel blocked filesystem I/O. Metadata/index writes outside the
snapshot policy remain outside its mutation guarantee.

Nine fixture contracts in `tests/test_mcp_broker.py` passed. Two additional
loopback HTTP/official SDK memory integrations passed. Official-SDK subprocess
stdio remains blocked on this host; real external adapters and Docker are unvalidated.


Current evidence and remaining boundaries: [2026-11-15 validation](development/governance-validation-20261115.md).
