# Serena integration preparation

Use the third-party Serena MCP implementation, installed into a separate environment;
do not copy its code into Keel or replace Keel's MCP client with a second protocol stack.
The current upstream packaging permits Python >=3.11,<3.15 and depends on MCP v2;
Keel's client remains on SDK v1. Separate environments avoid Python dependency
conflicts; actual wire-protocol compatibility still requires live discovery/call tests.

```powershell
python examples/setup_serena.py --output .keel/tool-checks/serena-setup-v1
```

This creates/reuses `.keel/tools/serena-venv`, installs `serena-agent` using existing uv,
records installed distribution versions, reads the installed CLI help, generates a
workspace-local launcher, and invokes Keel's generic discovery checker. No LLM is
called and no tools are authorized. Serena's documented SERENA_HOME is redirected
into `.keel/tools/serena-home`; its project cache/config may also be created in the
repository. It may download language-server dependencies. It is not an OS sandbox.

First installation resolves the available package version; the receipt records it.
Use `--version <exact-version>` for a specific release, `--no-install` to reuse only,
or `--no-discover` for installation-only diagnosis. Existing installs are reused unless
an explicit different version is requested. Existing output directories are not overwritten.
Installation and discovery logs are archived separately; inspect setup.json on failure.

After successful discovery, inspect `discovery/discovered-tools.json` and explicitly
choose the read-only symbol tool names actually present. Generate a runtime profile:

```powershell
python examples/configure_mcp_tools.py --connection .keel/tool-checks/serena-setup-v1/discovery-config.json --discovery .keel/tool-checks/serena-setup-v1/discovery/discovered-tools.json --server serena --tool <actual-tool-name> --role scout --read-only --output .keel/tool-checks/serena-readonly.json
```

Replace the placeholder with a reviewed actual tool name, not an assumed one. The
profile generator copies its actual input schema, excludes every unselected tool,
and writes input/config hash receipts. It cannot establish that an external tool is
read-only just from its name: operator review and server containment remain necessary.
Use `check_external_tool.py --tool ... --arguments-file ...` to verify a selected tool
before exposing it in a real Agent task. Do not open shell/edit/REPL tools for this trial.

Status: the user's terminal completed setup with Serena 2.0.0, initializing MCP and
discovering 29 tools, with no model calls or permissions granted by discovery.
`.keel/tool-checks/serena-readonly.json` was then generated from that actual catalog,
allowing only find_symbol, get_symbols_overview and find_referencing_symbols for scout.
The example query in `examples/mcp-serena-symbol-query.json` validates against the
discovered schema. The user's serena-query-v2 completed a real symbol query: ledger
fact 1 contains RecoveryController in keel/recovery.py, lines 62–212. This verifies
one LSP query, not coding-task improvement. Windows subprocess transport destructor
errors still appeared after success. The client now explicitly closes transports
owned by its request loop after SDK shutdown; success/error/timeout cleanup tests
pass, but a fresh Windows Serena run is required to verify those exit errors disappear.

The first query exposed an empty `language_servers` list in Serena's auto-generated
project config. Setup now checks Python projects (pyproject plus tracked Python files),
fills an empty server list via Serena's installed YAML dependency, and sets read_only.
Explicit existing nonempty server choices are preserved. The previous config and hash
receipt are archived before modification. Other languages can be selected using
`--language-server`. Initial LSP startup can download dependencies; discovery alone
does not establish that an LSP is configured or usable.

```powershell
python examples/check_external_tool.py --config .keel/tool-checks/serena-readonly.json --repo D:\keel --tool mcp__serena__find_symbol --arguments-file examples/mcp-serena-symbol-query.json --output .keel/tool-checks/serena-query-v1
```

Primary references:
- https://github.com/oraios/serena
- https://github.com/oraios/serena/blob/main/pyproject.toml
- https://github.com/oraios/serena/blob/main/src/serena/cli.py
- https://github.com/oraios/serena/blob/main/src/serena/config/serena_config.py
