# External tools: reuse through MCP, not vendor-specific recovery loops

Keel uses the optional official MCP Python SDK v1 (`.[mcp]`), rather than implementing
protocol messages. Existing stdio servers and Streamable HTTP endpoints share role
allowlists, timeout/global tool budget checks, server input-schema validation, result
size limits and evidence recording. SDK v2 is not yet supported by the dependency range.

Each server is operator-configured. The model selects only tool aliases and arguments;
it cannot install servers or supply executable commands/URLs. Credentials are references
to environment variable names; their values are resolved only at connection time.
Optional `input_schema` is exposed to the model and checked alongside the actual server
schema. Operator descriptions remain required; server descriptions do not grant authority.

Stdio example: `examples/mcp-compass.json`. It uses the selected terminal Python and
the repository as cwd. Ensure that interpreter can import Compass and that the repository
has a supported index. Absolute executable paths are preferable for deployment.
The Compass example enables its existing `--auto-update` option so stale indexes can
be refreshed automatically. This writes index/cache metadata, not source edits; it is
not an automatic repair policy for arbitrary external servers.

```powershell
python examples/check_external_tool.py --config examples/mcp-compass.json --repo D:\keel --tool mcp__compass__find_symbol --arguments-file examples/mcp-symbol-query.json --output .keel/tool-checks/compass-v1
```

This launches the configured server but does not invoke an LLM. Its ledger stores the
full response; the check output reports status/fact ID only. A new output directory is
required. Use an arguments file to avoid Windows PowerShell native JSON quoting issues.
On server tool errors, `mcp-tool-error.json` retains bounded untrusted server output.
The checker prints only a host-generated diagnostic and interpreter path; arbitrary
server error text is not echoed because it can contain credentials or repository data.

Remote configuration shape (replace endpoint/tool/schema with an actual server):

```json
{
  "docs": {
    "transport": "streamable-http",
    "url": "https://your-mcp-server.example/mcp",
    "headers_env": {"Authorization": "KEEL_MCP_AUTHORIZATION"},
    "tools": {
      "lookup": {
        "roles": ["scout"],
        "description": "Read documentation for the specified installed version.",
        "read_only": true,
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": false}
      }
    }
  }
}
```

The authorization variable contains the complete header value, e.g. Bearer plus token;
never put tokens in command arguments or URLs. Loopback HTTP is supported, remote
endpoints require HTTPS. stdio `env` similarly maps child variable names to existing
host variable names. No OAuth authorization flow or SSE legacy transport is implemented.

## Environment recovery

Add `--mcp-config path/to/servers.json` to the recovery command. The model sees the
configured diagnostic tools and may choose `action=tool`. Successful observations are
archived with evidence IDs and returned to the same ReAct loop. Failed calls are
observations, not successful evidence. Tool budgets remain shared.

Only scout-allowlisted tools explicitly marked `read_only=true` are accepted by the
environment recovery adapter. This flag is an operator assertion, not an OS sandbox:
an external server can have side effects. Use trusted read-only server profiles or run
servers in independently restricted containers. Generic external evidence proves that a
tool returned data, not that a particular target image was inspected or a cause proven.
For instance-specific conclusions, prefer the built-in image inspection provenance.

## Discover actual contracts before integration

```powershell
python examples/check_external_tool.py --config examples/mcp-compass.json --repo D:\keel --discover-server compass --output .keel/tool-checks/compass-discovery-v1
```

This initializes the configured server and uses SDK tools/list (including pagination),
without tools/call or an LLM. `discovered-tools.json` contains the actual names and
input schemas. Discovery can use a connection-only server config without a tools
allowlist; that config cannot execute tools. Inspect the returned contracts and add
only selected tools and roles to the runtime config. Read-only annotations and server
descriptions never authorize tools automatically. Discovery itself starts a server or
opens a remote connection, so use an operator-trusted executable/endpoint.

The schema-discovery lifecycle and subsequent explicitly allowed call are tested with
a real official SDK client/server over in-memory streams; this tests actual protocol
behavior without relying on child-process permission or live third-party services.

## What to reuse next

- Serena: evaluate as a read-only symbol/reference provider alongside Compass. Use
  actual tool names and schemas from the installed server, not guessed contracts.
- Context7: optional documentation evidence; historical versions must match the task.
- SWE-ReX: evaluate for a separate diagnostic sandbox/session backend. Its runtime
  server installation and deployment lifecycle differ from the official benchmark
  images, so it is not silently substituted into official grading. No SWE-ReX adapter
  or third-party server installation has been completed in this change.

References: https://github.com/modelcontextprotocol/python-sdk/tree/v1.x
and https://swe-rex.com/latest/usage/ .

Validation: official SDK HTTP connection/session path tested with mocked transport;
real Compass stdio test remains in the suite, but the current tool host returns
PermissionError when starting the SDK-managed process. This failure is retained;
live external-server interoperability must be checked in the user's terminal. No
paid model run or third-party server download was performed.
