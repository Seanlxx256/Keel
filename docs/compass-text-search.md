# Optional documentation/configuration search

The mixed-context experiment regressed on all five tasks when non-Python text
was forcibly alternated into Compass results. `search_text` therefore remains a
separate opt-in MCP tool. It does not change `search_code`, default discovery or
Keel's default configuration. A model may choose it through the existing Scout
tool catalog; no call is required and no new model-driven routing is claimed.

## Behavior and boundaries

- Start Compass with `--enable-text-search`; otherwise `search_text` is absent.
- Query Git-tracked docs/configuration from the current workspace. Supported
  types and omissions follow `compass.text_corpus`; Python results are excluded
  from this tool's output. No model or embedding service is called.
- Defaults: five candidate regions, 100 output lines, 16,000 source UTF-8 bytes.
  Explicit ceilings: 20 regions, 100 lines and 64,000 source bytes. Metadata is
  additional to the source-byte budget. Oversized individual lines are not cut
  into fabricated partial-line evidence. Truncation and usage are reported.
- Include paths, exact line ranges and content. Mark repository text untrusted;
  treat it as evidence, never as instructions to override runtime policy.
- Revalidate source bytes, incrementally refresh changed tracked files, and
  validate freshness after reading snippets. Parent and file symlinks are rejected.
- Store cache outside source, by default in the OS temporary directory keyed by
  resolved repository root. Explicit `--text-index` must also be outside source.
  The existing Python index is neither required nor updated by a text request.
  Process-only model credentials are not needed.

The profile authorizes only Scout. Planner/Implementer do not receive the tool.
Existing Keel gateway checks, call budgets, traces, evidence visibility and ledger
storage apply. Read-only describes source effects: the external cache is writable.
The server does not make retriever output trusted merely by returning it.

## Prepare and exercise

```powershell
Set-Location D:\keel
& 'D:/code/monocular_depth_estimation/.venv/Scripts/python.exe' examples/setup_compass_text.py --output .keel/tool-checks/compass-text-profile-v3
& 'D:/code/monocular_depth_estimation/.venv/Scripts/python.exe' examples/check_external_tool.py --config .keel/tool-checks/compass-text-profile-v3/config.json --repo D:/keel --tool mcp__compass__search_text --arguments-file examples/mcp-text-query.json --output .keel/tool-checks/compass-text-user-v1
```

Use fresh output directories. Setup installs nothing: it binds the selected
interpreter and absolute launcher path. The launcher imports the project from
its own location while `--repo .` follows each active Keel workspace. This avoids
accidentally querying D:/keel when a repair runs in another repository. Review
the generated profile before adding it through a task runner's `--mcp-config`.
Do not set `--require-external-tool` for a study intended to measure optional use.

## Verified evidence

Nineteen direct service, stdio, SDK-memory, role-policy, cache, byte-bound and
existing MCP regression checks passed. The actual project subprocess probe is
`.keel/tool-checks/compass-text-stdio-v2/probe.json`: the query returned
`pyproject.toml` and `docs/harness-environment-recovery.md`, 40 lines and 1,725
source bytes, without model/embedding calls.

The full Keel official-SDK stdio probe at
`.keel/tool-checks/compass-text-call-v1/check.json` hit PermissionError in this
execution environment. The named-pipe capability probe reports server WinError 5
and client WinError 2. An existing SDK subprocess regression fails at that same
transport boundary. That failed probe is retained separately.
The new gateway test instead uses real official SDK messages and the actual
Compass handler over SDK memory streams; raw stdio is separately exercised in
actual processes, including a different cwd.

The ordinary-terminal full SDK subprocess check subsequently succeeded:
`.keel/tool-checks/compass-text-user-v1/check.json`, with evidence in its
`ledger.sqlite` and `trace.jsonl`. The real Keel gateway returned fact 1 containing
`pyproject.toml` and `docs/harness-environment-recovery.md`: 40 source lines,
1,725 source bytes, and zero model/embedding calls. This validates the full
gateway-to-Compass stdio chain on that host. It is a manually requested tool
check, not evidence of autonomous tool selection or improved repair quality.

The project probe initially exposed Windows Git ownership-path handling; the
per-command `safe.directory` now uses normalized POSIX paths. No global Git or
permission settings were changed. Inventory errors become explicit tool errors.

The preceding mixed experiment is closed. Its original text-corpus source was
archived and hash-checked before these changes. Replaying its frozen plan using
the changed current implementation is intentionally refused; retain its old
scores and declare a new plan for future trials.

## Next evidence needed

Run a separately frozen matched-model/budget repair comparison: ordinary tools
versus optional text search. Record whether the model chose the tool, the query,
returned evidence, failures, costs and official repair grading. Include tasks
where docs/config are unnecessary, so unnecessary calls and displaced context
remain visible. Current integration tests do not establish autonomous tool-choice
quality, lower costs or improved repair success.
