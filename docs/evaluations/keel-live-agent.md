# Keel live agent and verifier sandbox validation

Two repeatable entry points now retain their fixtures and results:

- `python examples/run_keel_agent.py`: a live Ollama Scout/Planner/Implementer
  task, followed by independent command verification, declared-file/AST audit,
  exact expected source comparison and telemetry export checks. Output lives at
  `.keel/agent-smoke/<id>`; failures return nonzero and preserve artifacts.
- `python examples/verify_keel_sandbox.py`: a real Docker verifier probe using
  an already available Linux Python image. It checks UID/capabilities,
  no-new-privileges, mount flags and denied writes, writable temporary storage,
  IPv4 routes and unchanged host fixture. Output lives at
  `.keel/sandbox-probes/<id>`; missing prerequisites do not fall back to local.

Docker validation remains outstanding here: no Docker executable was found.
The attempted probe at `.keel/sandbox-probes/432979aabd2f4983b93a651feab10d68`
records this failure explicitly. These containers isolate verifier commands,
not Agent execution or external MCP subprocesses. Resource exhaustion, IPv6,
and general escape resistance are not established by this probe.

The live model is the existing `keel-chat` Ollama model, previously reported
as Qwen2.5-Coder-3B-Instruct Q4_K_M. The smoke task uses an 8192 context setting,
300-second wall time, 24 model calls, 40 tool calls, and a 120000-token budget.
The context setting now flows through `models.from_config`.

Real initial failures revealed:

- An unstructured Scout repeatedly recalled beyond end-of-evidence and used
  all 10 turns. Evidence: `.keel/agent-smoke/3e7719641d654da8a6d3c91e3edb1bcb`.
- Structured answers could still assert completion without making edits;
  independent verification correctly rejected the unchanged source.
- With the evidence gate enabled, a four-item plan made the correct edit but
  then repeated the same replacement, exhausting 24 model calls before final
  verification. Evidence: `.keel/agent-smoke/766ec18c741c476383a792abdd8ac27f`.
  Correct source alone is not recorded as a successful runtime run.

The resulting changes add role-specific structured final contracts, explicit
role instructions separating claims from observations, an optional
`require_evidence` gate (default false), a planner `max_work_items` cap (default
20, smoke task 1), and rejection of recall offsets outside stored evidence.
Planner output above the configured item cap fails before implementation,
including providers without structured output. Schema bytes enter model token
preflight accounting. Independent verification is still authoritative.

This is one synthetic migration fixture, not UpgradeBench or evidence of
broad task reliability. Historical failures remain available.
## Completed local live-model run

Final smoke execution `.keel/agent-smoke/2eb1360a46c249029e98b6e8ae1f6620`
passed all six checks in 44.797 seconds with 6 real model calls, one planned
work item, and 16 exported spans. API_VERSION changed from 1 to 2; greeting
behavior and all remaining source text matched the expected fixture exactly.
Independent acceptance returned zero and the declared-file/AST audit passed.
The actual verifier backend was local. This is not a live Docker result.

The result, task config, source fixture, changes.patch, trace.jsonl,
ledger.sqlite, spans.otlp.json and summary.json remain in that artifact directory.

Final regression: 203 tests, 198 passed, 5 optional-dependency skips, no failures. Compile and whitespace checks passed.
