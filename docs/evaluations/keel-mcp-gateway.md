# Keel MCP gateway milestone

The W6-7 gateway now accepts explicitly configured stdio MCP servers and
per-tool role allowlists. Agent sessions expose namespaced aliases only; server
commands and grants come from operator configuration. External responses enter
the existing session-scoped ledger and recall path. Gateway events include
transport, correlated start/end, duration, and status.

The optional `mcp` extra installs the official v1 SDK and JSON Schema validator.
The client follows the official SDK initialize/list/call/context-manager flow:
https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/clients/stdio_client.py

Calls include initialization, paginated discovery, server input-schema validation,
and teardown. Each attempt charges one tool call, with a request timeout capped
by remaining wall time. Startup cost is included; server-internal model/tool
costs are not accounted for. Cleanup can take additional time. Tool error payloads
are not presented as successful evidence. Successful decoded responses larger
than 1 MB are rejected before writing evidence. This is not a wire memory cap.

Validation on 2026-10-15:

- Full base-interpreter regression: 195 tests, 191 passed, 4 optional-dependency
  skips. A subsequently added SDK-boundary test was run separately below.
- Final MCP targeted suite under base Python: 3 passed, 2 SDK-dependent skips.
- SDK-boundary test under the installed MCP 1.30 virtual environment: passed;
  mocked transport/session verifies schema rejection before tools/call,
  server isError rejection, and context exit on failure.
- Actual Compass stdio integration was attempted under that environment and
  failed with PermissionError during pipe/process setup in this restricted
  execution environment. It is not counted as passed. The integration test
  remains enabled whenever the SDK is installed, including CI and user shells.
- Existing 12 agent tests passed after integration. Diff whitespace check passed.

Run in the user's activated environment:

```powershell
python -m unittest discover -s tests -p test_mcp_client.py -v
```

The real integration test builds a temporary Compass index, launches the actual
server, finds a symbol, rejects schema-invalid arguments, and makes a subsequent
successful request after the error. It does not use Ollama or public datasets.

This milestone does not establish OS sandboxing: MCP executables run with host
permissions. Only configure trusted processes. No remote HTTP transport or
sampling/elicitation bridge is provided. OTel and live sandbox validation remain
W6-7 work.
