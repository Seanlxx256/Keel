# Keel

A reliability runtime for long-horizon coding tasks.

Keel is a governance layer around coding-agent execution. It targets runtime failures such as wasted retries, timeouts, premature completion, and misleading validation. The goal is to measure improvements under a fixed model and budget.

Compass now has a Python-first index, a SQLite symbol/call/import graph, incremental extraction/embedding reuse, adaptive T0/T1/T2 retrieval, a stdio MCP server, and direct Keel integration. The early-stopping predictor and isolated concurrent workspaces remain planned.

## Current implementation

The runtime supports two modes:

- **Explicit:** execute an operator-supplied dependency graph and exact text replacements.
- **Agent:** use an Ollama model to inspect the repository, generate a dependency graph, and call scoped editing tools.

Scout, Planner, and each Implementer receive independent conversation histories. Work items execute sequentially. Verifier and Auditor are deterministic Python components. Critic currently records failure evidence and returns control to the operator; it does not retry automatically.

| Component | Available behavior |
| --- | --- |
| Task execution | DAG validation, sequential scheduling, per-item write scopes |
| Context ledger | SQLite facts, complete evidence storage, paginated recall |
| Read cache | Content-addressed file reads and duplicate-call counts |
| Retrieval | Exact lookup, BM25/vector fusion, heuristic escalation, bounded read-only model exploration |
| Budgets | Tool calls, model calls, token accounting, wall-clock checks |
| Static audit | Protected paths, Python AST invariants, selected test configuration checks |
| Execution audit | Optional pre/post JUnit comparison, test identities, skips, failures |
| Mutation probes | Optional bounded sampling of changed Python functions |
| Verifier execution | Local commands or an optional restricted Docker backend |
| Artifacts | Structured results, JSONL events, SQLite ledger, unified diff |

## Quick start

Python 3.11 or later is required. The runtime has no third-party Python dependencies.

From the repository root:

```powershell
python examples/demo.py
python examples/compass_demo.py
python examples/retrieval_demo.py
python examples/compass_closure_demo.py
python -m unittest discover -s tests -v
python -m keel --help
```

The demo creates a temporary repository, migrates a version constant, and saves artifacts under `.keel/demo-runs/<run_id>/`.

Run an explicit task against a **disposable working copy**:

```powershell
python -m keel run examples/task.json --repo D:/path/to/working-copy
python -m keel replay D:/path/to/working-copy/.keel/runs/<run_id>
python -m keel recall D:/path/to/working-copy/.keel/runs/<run_id> 1
```

The sample expects an `app.py` containing `API_VERSION = 1`. Keel modifies the supplied working copy directly. Failed runs retain completed edits for inspection.

## Model-driven tasks

Start an Ollama service and set `model.name` in `examples/agent-task.json` to a locally installed model that follows JSON instructions:

```powershell
python -m keel run examples/agent-task.json --repo D:/path/to/working-copy
```

Agent mode generates its own plan; omit `work_items`. Scout and Planner can list, search, and read files. Implementers can replace unique text in their declared existing UTF-8 files. File creation, deletion, arbitrary shell tools, and changes to acceptance commands are unavailable to the model.

Tool results are stored in full in the ledger. Conversation observations contain a preview of up to 4,000 characters and a fact ID. Recall is paginated and limited to facts observed by the current session. `.git` and `.keel` are unavailable through file-reading tools. Histories still accumulate within each bounded session; automatic context eviction is not implemented.

Requests use an input-byte estimate plus the output limit for budget preflight, followed by provider-reported token accounting. This estimate is not an exact tokenizer or a billing guarantee. Raw model replies and repository evidence are stored locally and may contain repository information. Connecting a remote endpoint sends the selected context to that endpoint.

Provider reference: [Ollama Chat API](https://docs.ollama.com/api/chat). Real-model quality has not been benchmarked; automated tests use scripted models and mocked HTTP responses.

## Verification and anti-cheat checks

Acceptance commands are operator-provided argument arrays and run without shell expansion. Existing configurations remain valid:

```json
"acceptance": [["python", "-m", "unittest", "discover", "-s", "tests"]]
```

Without a structured report, Keel can check exit codes and file changes but cannot establish how many tests ran. To enable test metadata checks, use a JUnit-producing command with the `{junit}` placeholder:

```json
"acceptance": [
  {
    "command": ["python", "-m", "pytest", "-p", "no:cacheprovider", "--junitxml={junit}"],
    "junit": true
  }
]
```

Pytest must already be installed in the execution environment. Keel runs these commands before edits to establish a baseline, then runs final acceptance. Baseline test failures are allowed, but a valid nonempty report is required. Each invocation gets a separate report directory; stale reports are not reused. Metadata checks count actual `<testcase>` elements, preserve baseline case identities and multiplicities, reject increased skips or zero executed cases, and reject final report failures even when the process exits successfully. These checks do not measure executed assertions or prove coverage, and a compromised test runner can fabricate XML.

Static checks run before each write and again after verification:

- Common test paths, test-runner files, and CI paths are protected.
- Python assertions cannot be removed or rewritten; newly added literal-true assertions and known skip/xfail constructs are rejected using ASTs, including common import aliases.
- Test-related configuration in `pyproject.toml`, `setup.cfg`, and `package.json` is protected while dependency changes remain possible.
- Final workspace changes must stay within declared target files.

These are intentionally conservative checks, not a general semantic proof. A legitimate assertion rewrite requires an operator-reviewed change outside this runtime. Dynamic monkey-patching, all language-specific test configurations, and obfuscated bypasses are not comprehensively covered.

### Optional mutation probes

Set `"mutation_samples": 1` (up to 20) to probe changed Python functions after acceptance passes. Keel samples supported literal return values or comparisons, temporarily injects a mutation, reruns acceptance, and restores the exact original bytes in a `finally` block. Probe results and commands are recorded separately. Surviving or inconclusive probes reject the run; no eligible functions produce an explicit `no_candidates` result.

This is a small deterministic mutation sample, not full coverage measurement. JUnit-enabled probes require preserved test collection and actual test failures; generic commands provide only a weaker nonzero-exit signal. Interpreter termination or machine failure can interrupt restoration, so use disposable working copies. Hard-linked edit targets are rejected.

## Optional Docker verifier

Local execution is the default and uses the current user's permissions. For Linux containers, add:

```json
"execution": {
  "backend": "docker",
  "image": "keel-test-env:local",
  "cpus": 1,
  "memory_mb": 512,
  "pids_limit": 128
}
```

Prepare the image with the repository's dependencies in advance. Keel never pulls images automatically and never falls back to local execution when Docker is unavailable. Acceptance executable paths must refer to programs inside the image.

The container runs with networking disabled, a read-only root filesystem and workspace, dropped capabilities, no-new-privileges, a non-root UID, CPU/memory/process limits, and bounded temporary shared-memory mounts. JUnit commands receive a separate writable report mount. Timeout handling attempts to force-remove only the uniquely named container and reports cleanup failure. Tests and builds must support a read-only source tree; cached files and build outputs need to go to `/tmp`. This backend currently offers no general writable build-output mount.

Reference: [Docker run documentation](https://docs.docker.com/reference/cli/docker/container/run/). Docker flag construction and timeout cleanup are tested with mocks. **Live container isolation has not been validated in the current environment, where Docker is unavailable.** The backend currently protects verifier execution only; it is not a complete agent sandbox or a hostile-code security guarantee.

Local command timeouts constrain the immediate process, not all descendants. Model HTTP timeouts and application budget checks are also not operating-system hard limits. Local commands inherit the host environment. Only the operator chooses acceptance commands and execution settings.

## Run artifacts

Each run produces:

- `result.json`: work-item outcomes, verification and audit evidence, budgets, failure attribution.
- `trace.jsonl`: ordered role, tool, model, verification, and mutation events.
- `ledger.sqlite`: facts, original observations, model replies, and read-cache entries.
- `changes.patch`: changes to declared text targets.
- `reports/`: baseline, final, and mutation JUnit reports when enabled.

Exit codes: `0` for a passed run, `1` for a recorded failed run, and `2` for invalid configuration or CLI usage. A passed run means the configured checks passed; report fields state which checks were enabled.

## Roadmap

- Validate Docker isolation in a real Linux-container environment and strengthen resource/process control.
- Expand adversarial audit evaluation and mutation operators; measure false positives and misses.
- Complete Compass public benchmark adapters, calibrated routing, cross-encoder reranking, and broader MCP client validation.
- Add isolated concurrent workspaces, bounded Critic retries, and richer context management.
- Export OpenTelemetry spans, collect labeled trajectories, and train the early-stopping predictor.
- Run public benchmarks and controlled ablations under fixed models and budgets.

No benchmark improvements or production reliability claims are reported yet.

## Compass index prototype (W1–2)

Compass is a separate package in this repository. The current milestone indexes Python functions, async functions, classes, and methods. Each chunk includes its original code, signature, docstring, qualified name, parent symbol, and line range. Retrieval text contains the path, qualified name, signature, and docstring; raw code is kept separately for display. Generated responsibility descriptions are not implemented yet.

Tree-sitter supplies structural byte ranges, with Python AST supplying Python-specific metadata. The optional `python-ast` backend uses stdlib ranges and must be selected explicitly; missing dependencies never cause a silent fallback.

Install optional packages when package-registry access is available:

```powershell
python -m pip install -e ".[compass,compass-vectors]"
python -m compass index --repo . --parser tree-sitter --vectors lancedb --embedding hash
```

The `hash` embedding is deterministic **lexical feature hashing, not a learned semantic model**. It supports storage and query smoke tests without a downloaded model. For semantic embeddings, configure an existing Ollama embedding model:

```powershell
python -m compass index --repo . --parser tree-sitter --vectors lancedb --embedding ollama --embedding-model YOUR_EMBEDDING_MODEL
```

Embedding input is sent to the configured endpoint, which defaults to localhost. The embedding endpoint is used only when explicitly selected. Model name and endpoint are recorded, but model-weight digest pinning is not implemented: rebuild if a model tag changes.

A dependency-free path exercises SQLite symbols, graph linking, and an exact cosine scan over stored hash vectors:

```powershell
python -m compass index --repo . --parser python-ast --vectors sqlite --embedding hash
python -m compass symbol --repo . RepositoryIndex
python -m compass context --repo . examples/compass_demo.py 20
python -m compass search --repo . "repository symbol index" --limit 5
python -m compass status --repo .
```

For `context`, choose a line inside the function or class of interest; a line outside any symbol returns an empty result. Use `--vectors none` to build only the symbol and graph index. The SQLite vector backend is a small exact-search reference implementation, not a substitute for LanceDB scalability. These vector queries are not the planned T1 hybrid retriever.

The graph links statically identifiable lexical calls, imported aliases, relative imports, and candidate `self`/`cls` method calls. Unresolved or ambiguous targets are stored explicitly; Compass does not infer arbitrary receiver types, resolve re-exports, or guarantee dynamic dispatch. Imports are stored with scope and repository-module resolution where available. Module names assume the repository root or a leading `src/` directory; custom source roots are not configured yet.

Indexes live under `.compass/generations/<id>/`, with a SQLite database and optional LanceDB files. Builds publish a generation through an atomic manifest replacement only after parsing, embeddings, and source consistency checks complete. Failed builds leave the previous generation selected. Old and failed generations remain on disk; automatic garbage collection is not implemented.

Each generation records the indexed Python-source fingerprint and available Git HEAD. Query sessions check freshness on open; stale indexes refuse code/graph/vector queries until refreshed. Incremental refresh is described below. Sessions do not continuously watch edits after opening. Generated directories such as `.git`, `.keel`, `.compass`, virtual environments, `node_modules`, `tmp`, `build`, and `dist` are excluded. This is a fixed exclusion list, not a `.gitignore` interpreter. Symlinked entries are not followed. Invalid UTF-8, syntax errors, and Python files over 1 MB appear in diagnostics and mark the index incomplete.

All query results include index identity, freshness, completeness, and uncalibrated `confidence: null`. No retrieval-quality or latency improvement is claimed. Multi-language grammars, cross-encoder reranking, and formal CORE-Bench/SWE-Explore adapters remain unimplemented. The following milestones build on this index.

**Validation status:** Python AST + SQLite symbols/graph/hash-vector paths are tested locally. The current environment cannot install tree-sitter/LanceDB because package-network access is unavailable; their real integration tests are present but skipped until dependencies are installed. Ollama embeddings are tested with mocked HTTP responses, not a live embedding model.

Implementation references: [py-tree-sitter](https://github.com/tree-sitter/py-tree-sitter), [LanceDB quickstart](https://docs.lancedb.com/quickstart), and [Ollama embeddings](https://docs.ollama.com/api/embed).

## Adaptive retrieval prototype (W3-4)

`retrieve` runs a cascade; `search` remains the raw vector-only query command:

```powershell
python -m compass retrieve --repo . RepositoryIndex
python -m compass retrieve --repo . "validate embedding vectors" --mode t1 --limit 5
python -m compass retrieve --repo . "which callers depend on repository indexing" --model YOUR_CHAT_MODEL
```

- **T0:** a unique exact symbol match or an exact indexed file path. Ambiguous symbol names fall through to T1 in adaptive mode.
- **T1:** a local BM25 reference implementation over chunk metadata and code, plus the configured vector backend, merged by reciprocal rank fusion (RRF). Results retain channel/rank provenance. An index without vectors runs a clearly labeled BM25-only path. Cross-encoder reranking is not yet implemented.
- **Upgrade gate:** evaluate top relevance, top-candidate score entropy, lexical/vector top-10 overlap, file span, and index completeness after T1. Thresholds are configurable heuristics; they have not been calibrated on a held-out benchmark. `confidence` stays null. Hash-vector signals are lexical smoke-test signals, not semantic confidence.
- **T2:** an explicitly configured chat model may add query terms while preserving the original API/error anchors, read paginated candidate code, traverse resolved caller/callee edges, and select discovered symbol IDs. It cannot write files, run shell commands, or access arbitrary paths. Steps, discovered nodes, graph hops, output size, model calls, tools, tokens, and request time are bounded. A missing model records `model_unconfigured` and returns T1 evidence without pretending T2 ran; a step limit is reported explicitly. Hard budget exhaustion fails the request.

Pass `--mode t0`, `--mode t1`, or `--mode t2` for comparisons. T2 also runs T1 to obtain its seeds. `--model` selects an Ollama chat model and is separate from the embedding model used during indexing. No chat call is made unless T2 is entered. Optional limits include `--max-model-calls`, `--max-tool-calls`, `--max-tokens`, and `--max-wallclock`. These are application limits, not operating-system resource isolation. Local BM25 and exact SQLite vector search scan the corpus and are intended as reference implementations.

Use `--routing path/to/routing.json` to override fields such as `min_relevance`, `min_overlap`, `max_entropy`, `max_files`, `candidates`, `max_steps`, `max_nodes`, and `graph_hops`. Invalid settings fail rather than silently resetting. Responses include the executed tier, gate signals, upgrade reasons, route trace, per-request counters, latency, and index identity. Token counters cover chat-model calls only; embedding tokens are not available from this interface. Vector query counts are reported separately. Routing latency excludes opening the index and its initial freshness scan; evaluation latency also includes retriever setup.

### Keel integration

Build a fresh Compass index before enabling this configuration in a Keel task:

```json
"retrieval": {
  "provider": "compass",
  "allow_t2": false,
  "routing": {"max_nodes": 40, "max_steps": 4}
}
```

`search_code` then uses the cascade; `find_symbol` and `get_context` become available to read-capable roles. Gate decisions, exploration replies, and observations are archived in the existing ledger and trace. All exploration calls share the run's budget. Agent-mode tasks with `allow_t2: true` reuse their configured chat model for T2. Existing tasks default to literal text search.

Keel currently uses an in-process integration rather than an MCP gateway. Each tool call opens a new index session, so edits invalidate subsequent Compass queries. By default, Keel reports stale-index errors; set `retrieval.auto_update: true` to enable incremental refresh between calls. Index refresh events are archived in the run ledger and trace. Compass tool results are bounded previews in role contexts, with complete observations retained in the ledger.

### Offline evaluation scaffold

Evaluate normalized JSONL records with `id`, `query`, nonempty repository-relative `relevant_files`, and an optional `source` label:

```powershell
python -m compass evaluate --repo . --dataset examples/retrieval-queries.jsonl --output .keel/retrieval-evaluation.json
```

The included dataset is a **three-query synthetic self-repository smoke fixture**, not CORE-Bench or SWE-Explore. The evaluator reports binary file Hit@K, Recall@K, NDCG@K, retrieval latency, chat tokens/calls, tool/vector query counts, failures, deferred upgrades, and recall regret relative to the evaluated modes. Rankings deduplicate files within the top-K returned symbol results; this granularity must be aligned before comparing with any public benchmark. Output paths must be new files.

Use `--modes t0 t1 t2 adaptive --model YOUR_CHAT_MODEL` for a full configured-tier comparison. Limits apply separately to each query/mode; the total experiment is not covered by one shared budget. The reference oracle is limited to the modes actually run. The report explicitly sets `public_benchmark_verified: false`. This is an evaluation scaffold, not a completed Pareto experiment or a claim of benchmark improvement. Canonical public-data loaders, split validation, parameter calibration, representative repetitions, and trained-reranker/live-model quality validation remain future work.

The synthetic demo (`python examples/retrieval_demo.py`) exercises T0, T1, and a scripted three-step T2 graph exploration without API access. Retrieval references: [LanceDB hybrid search and RRF](https://docs.lancedb.com/search/hybrid-search/) and [Ollama Chat API](https://docs.ollama.com/api/chat).

## Compass integration milestone (W5)

### Incremental refresh

**Index schema is now version 2. Rebuild older indexes once** before using updates or the server:

```powershell
python -m compass index --repo . --parser python-ast --vectors sqlite --embedding hash
python -m compass update --repo .
```

`update` retains the selected parser, embedding provider, and vector backend. It scans Python content hashes, reuses unchanged extraction caches, parses added/modified files, removes deleted symbols, and relinks the complete graph. It is content-hash driven, not a Git-diff-only fast path, so it also detects unstaged and untracked Python changes. A no-op preserves the selected generation.

Embedding text includes up to 32 statically resolved callees' qualified signatures. A signature change therefore invalidates relevant caller embeddings even when the caller's source is unchanged. Embeddings are reused by exact retrieval-text equality; a body-only change can reuse its vector because raw code is a separate display representation. This is signature dependency tracking, not transitive semantic-impact inference or generated responsibility-description invalidation.

All refreshes publish a new immutable generation after consistency checks. Unchanged files are not reparsed and unchanged retrieval text is not re-embedded, but the graph, SQLite snapshot, and LanceDB table are rewritten. Portable embedding caches are also stored in SQLite, including for the LanceDB backend. This favors atomic publication over in-place storage updates. Full source hashing, graph relinking, disk copying, old-generation retention, and duplicate vector storage remain scalability costs.

Update reports include parsed/reused files, additions/modifications/deletions, reused/new vectors, invalidated symbols, and the parent generation. Failed refreshes retain the previous manifest; stale data is not silently served. Run a full build after changing parser packages, extraction logic, or embedding weights/settings. There is no cross-process update lock or automatic model-weight digest detection yet.

### MCP stdio server

```powershell
python -m compass serve --repo D:/path/to/working-copy --auto-update
```

The repository-bound server is named `repo-intel` and exposes:

| Tool | Purpose |
| --- | --- |
| `find_symbol(name, limit)` | Exact symbol lookup |
| `search_code(query, limit)` | Adaptive retrieval |
| `impact_analysis(change, limit)` | Candidate change-impact exploration through T2; requires `--model` |
| `get_context(file, line, limit)` | Containing symbol and graph neighbors |

Omit `--auto-update` to fail on stale indexes. Missing indexes and incompatible schemas require an explicit initial full build. Add `--model YOUR_CHAT_MODEL` to enable T2; this can send retrieved code to the configured model endpoint. All tool arguments are validated, and requests cannot switch the server's repository. No source-edit or command-execution tool is exposed. Auto-update writes only derived index artifacts. Budgets apply per tool request; there is no process-lifetime spending limit.

This is a dependency-free, synchronous JSON-RPC stdio implementation supporting MCP protocol versions `2025-11-25`, `2025-06-18`, and `2024-11-05`. It handles initialization, initialized notifications, pings, tool listing/calls, structured/text results, input limits, errors, UTF-8 framing, and EOF shutdown. Standard output is reserved for newline-delimited protocol messages. It does not provide HTTP transport, tasks, sampling, progress streams, concurrent execution, or preemptive cancellation. Running model/index calls complete or hit their own timeouts before another message is processed.

For a client that accepts `mcpServers`, an illustrative entry is provided in `examples/mcp-config.json`. Install this package in the chosen Python interpreter first; the example is not automatically registered in any application. Protocol and real-subprocess tests pass locally, but official SDK/client interoperability and live LanceDB/model deployment have not been validated.

Protocol references: [MCP lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools), and [stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).

### Cost-quality reports

Export an existing normalized evaluation report into a new directory:

```powershell
python -m compass report --input .keel/retrieval-evaluation.json --output-dir .keel/compass-comparison
```

Outputs are `report.md`, `comparison.csv`, and `frontiers.json`. Frontiers maximize recall, NDCG, or file-hit rate while minimizing observed latency, chat tokens, model/tool calls, or vector-query count. Failed, deferred, and step-limited modes are excluded. Equal cost/quality ties remain nondominated. Reports preserve index and dataset labels and explicitly note measurement limits; they do not establish statistical significance, embedding-token costs, public-benchmark validity, or production savings.

Evaluation JSON now includes normalized queries/labels, a dataset fingerprint, routing settings, limits, and the configured chat-model name to support review. Model-weight pinning and repeated-trial uncertainty remain future work. The end-to-end `python examples/compass_closure_demo.py` demonstrates incremental signature invalidation, an actual MCP subprocess exchange, and a synthetic report export without optional packages or API calls. This closes the local W5 prototype; representative Pareto experiments and external client validation remain outstanding.
