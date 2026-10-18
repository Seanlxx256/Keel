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

## Optional tool-assisted localization

Localized-proposal mode now accepts `localization_tool_steps` (0 by default,
1–12 when enabled). It runs the ordinary Scout AgentSession before catalog/anchor
selection. Authorized MCP tools and local search/read tools share the run's existing
budgets. Tool errors return as observations; the model can change its query or use
local tools. A local exploration turn limit falls back to catalog selection; global
budget failures propagate. Final summaries and up to four bounded evidence previews
are untrusted inputs, and writable catalog/AST checks remain authoritative.

Every MCP tool authorized for Scout must explicitly declare read_only when this
option is enabled. This is an operator declaration, not an OS sandbox. Tool use is
model-selected, not forced. The trace records `localization_tool_exploration` and
normal gateway calls; absence of an MCP call means no external-tool benefit was tested.

`run_swebench_task.py` accepts `--mcp-config <authorized-profile.json>` and
`--localization-tool-steps 6`, records the profile hash and checks it during execution.
Without the flag the previous workflow remains unchanged. These extra calls consume
the same 30-model-call/80-tool-call limits, rather than receiving an additional budget.

Serena's generated launcher now uses `--project .`: the MCP client's cwd is the
active repair workspace. Old launchers must be regenerated with setup_serena.py
`--no-install --no-discover` before reuse across repositories. Each target still
needs a functioning Serena language-server configuration. Failure is observable and
local search remains available; this change does not prove all target LSPs work.

Validation: scripted integration tests cover an MCP failure followed by local source
inspection, evidence reaching catalog selection, actual patch/acceptance completion,
local turn-limit fallback, global budget enforcement and read-only policy rejection.
Real Serena-assisted repair effectiveness and paired performance remain unmeasured.

The astropy-14508-serena-v1 exploratory run failed: official_resolved=false,
29 model calls and 157106 tokens. Its eight gateway requests were all local tools;
there was no Serena call, so it is not a measurement of Serena retrieval quality.
Scout consumed 23 calls / 132964 tokens. Repeated exploration plus full catalog
selection was an observed cost, not proof of the sole cause of repair failure.

After this diagnosis, exploration is reused only for an unchanged source snapshot
and investigation goal (host selection-error retries do not restart it). New source
or a new diagnostic goal triggers fresh inspection capped at three turns, carrying
only previous candidate file names, not old evidence. Valid nonempty Scout candidate
paths with observed evidence bypass the redundant file-selection call; writable
catalog membership and fresh AST anchor validation still apply. Invalid candidates
fall back to catalog selection. Reports now expose `external_tool_calls` per alias
as completed/failed/denied gateway requests, not server-internal execution counts.
No requests means no external-tool effectiveness claim. Real rerun pending.

For an explicit integration test, add `--require-external-tool` alongside
`--mcp-config`. Runtime config uses `localization_require_external: true`.
This opt-in mode requires at least one authorized Scout MCP gateway attempt before
local fallback; the first response schema excludes local tools and final answers,
and host checks enforce this even with an unstructured provider. A failed attempt
unlocks local fallback, but does not count as success. Exhausting exploration turns
without an attempt reports a failure instead of silently claiming validation.
Replanning does not force the same requirement repeatedly once attempted in the run.

`external_tool_validation` records required/attempted/successful_requests. These
are host gateway outcomes; schema errors, connection failures and empty server
results still require inspection before claiming a useful LSP query. This mode
changes tool selection policy, so compare it separately from automatic selection;
it does not establish a retrieval or repair success-rate improvement.

The astropy-14508-serena-required-v1 run completed one get_symbols_overview request;
its ledger contains Card and _format_float among the real returned symbols. The run
failed with policy_denied because Serena created .serena config/cache files inside
the source checkout. Official resolved remained false; this is not a repair success.

The launcher now prepares a per-workspace SERENA_HOME under
`.keel/tools/serena-workspaces/<sha256-of-absolute-workspace>/`, and sets installed
Serena's `project_serena_folder_location` to its external project-data directory.
That directory is created before project loading, preventing Serena's fallback to
an existing repository .serena folder. The generated external project config is
read-only, and language detection completes synchronously. Source audit exclusions
are unchanged. Existing repository .serena files are neither removed nor modified.
The installed config API must honor relocation or startup fails explicitly.

Real Serena 2.0 config/project initialization tests verify external metadata writes,
unchanged source trees (including existing .serena config), repeat startup and
distinct state for identically named workspace folders. A fresh-process launcher is
necessary because SerenaPaths caches its home. Actual post-fix MCP/LSP trial pending.

Primary references:
- https://github.com/oraios/serena
- https://github.com/oraios/serena/blob/main/pyproject.toml
- https://github.com/oraios/serena/blob/main/src/serena/cli.py
- https://github.com/oraios/serena/blob/main/src/serena/config/serena_config.py
