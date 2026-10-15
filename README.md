# Keel

A reliability runtime for long-horizon coding tasks.

Keel is a governance layer around coding-agent execution. It targets runtime failures such as wasted retries, timeouts, premature completion, and misleading validation. The goal is to measure improvements under a fixed model and budget.

Compass now has a Python-first index, a SQLite symbol/call/import graph, incremental extraction/embedding reuse, adaptive T0/T1/T2 retrieval, a stdio MCP server, and direct Keel integration. The early-stopping predictor and isolated concurrent workspaces remain planned.

## Current implementation

The runtime supports two modes:

- **Explicit:** execute an operator-supplied dependency graph and exact text replacements.
- **Agent:** use an Ollama model to inspect the repository, generate a dependency graph, and call scoped editing tools.

Scout, Planner, and each Implementer receive independent conversation histories. Work items execute sequentially. Verifier and Auditor are deterministic Python components. Critic currently records failure evidence and returns control to the operator; it does not retry automatically.

Execution now has an explicit sequential role state machine. Successful runs pass through Scout, Planner, Implementer, Verifier and Auditor; failures close through Critic. Optional baseline verification is a distinct Verifier phase that returns to Scout and cannot substitute for final verification. Invalid transitions are rejected. `result.json` includes `state_machine` with terminal outcome and per-role phase/status/duration; JSONL records `role_entered`, `role_exited` and `state_machine_finished`. Supplemental operator queries may return an agent-generated plan to Scout before plan validation. Unexpected exceptions retain a failed lifecycle artifact and propagate their original exception; this is not automatic recovery. Lifecycle events are correlated with local OTLP/JSON spans; Collector upload and cross-process propagation remain planned.

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

Reference: [Docker run documentation](https://docs.docker.com/reference/cli/docker/container/run/). Docker flag construction and timeout cleanup are tested with mocks. Live verifier-container checks passed on 2026-10-15 (UID, capabilities, mount flags, denied writes and IPv4 routes); a real CPU-model/Docker smoke task also passed. The backend currently protects verifier execution only; it is not a complete agent sandbox or a hostile-code security guarantee.

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

- Extend validated verifier-container isolation to Agent/MCP execution and strengthen resource/process control.
- Expand adversarial audit evaluation and mutation operators; measure false positives and misses.
- Complete Compass public benchmark adapters, calibrated routing, cross-encoder reranking, and broader MCP client validation.
- Add isolated concurrent workspaces, bounded Critic retries, and richer context management.
- Extend local OTLP export with SDK/Collector integration, collect labeled trajectories, and train the early-stopping predictor.
- Run public benchmarks and controlled ablations under fixed models and budgets.

No benchmark improvements or production reliability claims are reported yet.

The first public-data BM25 reference run is recorded in [the Flask evaluation note](docs/evaluations/core-flask-baseline.md): one query over 1,000 documents, with zero NDCG@10 and Recall@100. A full-ranking diagnostic placed the positive document at rank 225. This small selected export is not a full-cascade or official benchmark result.

A subsequent [12-repository Verified Level-2 baseline](docs/evaluations/core-verified-baseline.md) completed 173 sampled queries over three repetitions: query-weighted NDCG@10 **10.0514%** and Recall@100 **29.0425%**. All repositories passed; one identical xarray label duplicate was deduplicated with provenance retained. These are local BM25 reference results, not official leaderboard or full-cascade scores.

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

Historical triple-quoted docstrings containing malformed `\u`/`\U` escapes (for example a literal Windows `DOMAIN\username` path) have a narrow indexing compatibility path. It activates only after a Unicode-escape AST error, repairs an in-memory AST view without changing byte positions, confirms that every repaired literal is a module/class/function docstring, and restores its literal text. Tree-sitter and emitted code still use the original bytes. Ordinary runtime strings, other syntax errors, and unsupported Python-2 grammar remain rejected. This permits lexical indexing; it does not make the original source executable under Python 3. The public runner rebuilds incomplete indexes rather than reusing their old diagnostics after a parser fix.

Indexes live under `.compass/generations/<id>/`, with a SQLite database and optional LanceDB files. Builds publish a generation through an atomic manifest replacement only after parsing, embeddings, and source consistency checks complete. Failed builds leave the previous generation selected. Old and failed generations remain on disk; automatic garbage collection is not implemented.

Each generation records the indexed Python-source fingerprint and available Git HEAD. Query sessions check freshness on open; stale indexes refuse code/graph/vector queries until refreshed. Incremental refresh is described below. Sessions do not continuously watch edits after opening. Generated directories such as `.git`, `.keel`, `.compass`, virtual environments, `node_modules`, `tmp`, `build`, and `dist` are excluded. This is a fixed exclusion list, not a `.gitignore` interpreter. Symlinked entries are not followed. Invalid UTF-8, syntax errors, and Python files over 1 MB appear in diagnostics and mark the index incomplete.

All query results include index identity, freshness, completeness, and uncalibrated `confidence: null`. No retrieval-quality or latency improvement is claimed. Multi-language grammars and cross-encoder reranking remain unimplemented. Local CORE-Bench/SWE-Explore format adapters are available below; official evaluator parity and public-data runs remain unverified. The following milestones build on this index.

**Validation status:** AST/SQLite paths and real tree-sitter/LanceDB integrations have passed local checks. Imported Ollama models have passed live embedding and T2 smoke checks; automated model tests still use mocks/scripted replies. See the evaluation notes for the scope of actual public-data measurements. Native dependency availability depends on the selected Python environment.

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

Use `--modes t0 t1 t2 adaptive --model YOUR_CHAT_MODEL` for a full configured-tier comparison. Limits apply separately to each query/mode; the total experiment is not covered by one shared budget. The reference oracle is limited to the modes actually run. The report explicitly sets `public_benchmark_verified: false`. This is an evaluation scaffold, not a completed Pareto experiment or a claim of benchmark improvement. The separate canonical-format adapters below preserve document and region labels. Official evaluator parity, split validation, parameter calibration, representative repetitions, and trained-reranker/live-model quality validation remain future work.

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


## Canonical benchmark formats

These commands consume local exports. They do not download data, authenticate its origin, or establish official scores. Reports record input SHA-256 hashes and a declared revision, and retain `public_benchmark_verified: false`.

For a repository export from [CORE-Bench](https://github.com/zhangfw123/CORE-Bench-Eval), provide `corpus.jsonl` and `queries.jsonl` with canonical `_id`/`text` fields, plus `qrels.jsonl` (`query_id`, `corpus_id`, `score`) or BEIR `qrels/test.tsv`:

```powershell
python -m compass benchmark core --data-dir D:/datasets/core/repository --revision DATA_REVISION --level 2 --output .keel/core-reference.json
```

This is a shared Compass BM25 **document baseline**, not the full T0/T1/T2 cascade. It preserves original document IDs, graded labels, and per-query `filtered_corpus_id` temporal candidates. Filtering occurs before ranking truncation; corpus statistics use the complete supplied corpus. Metrics are linear-gain NDCG@10 and Recall@100. Unjudged queries are listed and excluded; invalid references and positive judgments outside temporal candidates fail. The default 200,000-document limit fails rather than silently truncating. `--max-queries` produces an explicitly labeled sample. Official evaluator parity has not been established.

For [SWE-Explore-Bench](https://github.com/Qiushao-E/SWE-Explore-Bench), select one instance and an explicit clean Git checkout at its base commit:

```powershell
python -m compass index --repo D:/snapshots/project --parser python-ast --vectors sqlite --embedding hash
python -m compass benchmark swe --dataset D:/datasets/swe.jsonl --instance INSTANCE_ID --repo D:/snapshots/project --issue-map D:/datasets/issues.json --commit-map D:/datasets/commits.json --line-budget 300 --mode adaptive --output .keel/swe-reference.json
```

Issue and commit maps are JSON objects keyed by instance ID; omit them when the record supplies `problem_statement` and `base_commit` (or `meta.base_commit`). Dataset-provided repository paths do not select the checkout. Tracked edits and untracked source inputs, including Git-ignored files, are rejected; generated index/cache directories are allowed. Keep dataset exports outside the checkout. Retrieval receives only the issue text, with an 8,000-character query limit; gold labels are used for scoring afterward.

The adapter validates file/region bounds, handles EOF regions, exports ranked regions within the line budget, and computes a reference subset of line precision/recall/F1, core-file hit rate, context efficiency, and first useful hit. Context packing caps each symbol prefix at 32 lines and skips already emitted lines, so a long function cannot consume the entire default budget and overlap does not waste it. Reports record this policy, returned candidate ranks/ranges, and full-range candidate diagnostics computed after retrieval. Candidate diagnostics are not emitted-context quality scores and do not enter model prompts or routing. Sweep events retain the initial hybrid ranking before T2 selection. Non-Python gold files stay in the denominator and are reported as unindexed. Current retrieval is Python-only; hash embeddings are lexical. These limitations prevent treating the result as an official SWE-Explore score or a complete public benchmark run.

## Real integration validation

Install optional integrations in an environment with package access:

```powershell
python -m pip install -e ".[compass,compass-vectors,validation]"
python -m compass validate --require-all --output .keel/integration-validation.json
```

The probes exercise real tree-sitter extraction and incremental updates, LanceDB persistence/search/vector reuse, and an official Python MCP SDK client against the stdio subprocess (discovery, structured results, refresh, tool errors, and ping). SDK validation currently targets the maintained [v1 client API](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x), pinned below v2. It does not validate SDK v2.

Each component reports `passed`, `failed`, or `unavailable`, with installed versions and evidence. Missing libraries never count as passes. `--require-all` exits 1 for either unavailable or failed integrations; without it, unavailable components are reported but only failed probes cause exit 1. Output files must be new. Select probes with `--components tree_sitter lancedb mcp_sdk`.

The GitHub Actions workflow in `.github/workflows/compass-integrations.yml` installs the extras, requires all probes, runs regression tests on Windows and Linux, and archives validation evidence. Adding this workflow does not establish that a hosted run has passed. Windows validation has passed for tree-sitter 0.26.0, tree-sitter-python 0.25.0, and LanceDB 0.40.0. The operator also confirmed the official MCP SDK 1.30.0 probe passes with protocol 2025-11-25; the restricted agent environment cannot create the SDK's Windows asynchronous subprocess pipes. Hosted CI and a complete operator-side regression run remain separate checks.


## Repeated CORE reference batches

On Windows, prepare all 12 repositories from the pinned Verified Level-2 export and run a batch in one command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\examples\run_core_verified_batch.ps1
```

The script pins revision `23da5d97a8a4495d4bd6d5616aa86d5a12a60699`, requires exactly 12 complete repositories, downloads their full corpora/queries/qrels, pins input hashes in a manifest, and invokes `core-batch`. Defaults are at most 20 judged queries per repository, seed 42, and three timing repetitions. Actual query counts may be lower than the limit. This remains a selected sub-dataset BM25 reference rather than a full CORE or cascade result.

Downloaded files are cached under `.keel/datasets/core/<revision>/`; reuse requires matching revision, remote path, byte size, and a local SHA-256 receipt. Receipts check local integrity, not trusted origin. Each run writes a new directory under `.keel/core-verified-batch/`, containing selection metadata, the manifest, API listing, evaluation log, and `results/batch.json` plus `results/datasets.csv`. Downloads retry twice; rerunning retains completed valid files. Unfinished individual files restart. The script stops before evaluation if data preparation fails, and it reports a nonzero exit code for failed or partial evaluation.

The script enables live progress on stderr while keeping final JSON stdout in `evaluation.log`. `results/progress.jsonl` records stages, repository/repetition/query counters, failures, and a heartbeat every 10 seconds during blocking work. `results/datasets.jsonl` checkpoints completed or failed repositories before the final summary is written. A heartbeat reports that the process is alive and its last stage, not an estimate of remaining time. Direct `core-batch` users can enable console messages with `--progress`; the JSONL progress log is always written. Progress logging adds some measurement overhead.

Identical repeated query/document/grade judgments are deduplicated and counted as `identical_duplicate_qrels`; they do not multiply relevance. Conflicting duplicate grades remain errors. This handles the one identical duplicate found in the pinned xarray export without changing corpus inputs or scores.

Use `-MaxQueries 20 -Repeats 1 -Seed 42` for a faster first pass. Once the complete cache exists, `-Offline` reruns preparation and evaluation without contacting Hugging Face. `-PythonCommand` can select an explicit Python executable; otherwise the active environment's `python` is used. `-DownloadTimeoutSeconds` adjusts each download attempt's timeout (default 300 seconds). The script uses `curl.exe`, without requiring the Hugging Face CLI.

Create a manifest outside the dataset checkouts. Paths are relative to the manifest file; names must be unique, and aliases of the same directory are rejected:

```json
{
  "version": 1,
  "benchmark": "core",
  "datasets": [
    {"name": "repository-a", "data_dir": "data/LEVEL-2/dataset/repository-a", "revision": "DATA_REVISION", "level": 2},
    {"name": "repository-b", "data_dir": "data/LEVEL-3/dataset/repository-b", "revision": "DATA_REVISION", "level": 3}
  ]
}
```

```powershell
python -m compass benchmark core-batch --manifest D:/datasets/core-manifest.json --output-dir .keel/core-batch-001 --repeats 3 --max-queries 20 --seed 42
```

Omit `--max-queries` to evaluate every judged query. Sampling is stable under JSONL reordering and uses query IDs, dataset names, and the seed, without inspecting relevance labels. The corpus is never sampled. Each repetition rebuilds BM25; elapsed totals include scorer construction and retrieval, while OS caches remain uncontrolled. Quality is counted once per query, rather than treating timing repetitions as independent quality evidence.

Outputs include `batch.json`, `datasets.csv`, and one canonical evaluation JSON per dataset/repetition. Reports retain selected query IDs, declared revisions, input/implementation/manifest hashes, timing mean and standard deviation, query-weighted means, repository means, and separate Level-2/Level-3 aggregates. Combined means describe only the manifest's selected exports. Failed datasets are visible and excluded from means; any failure makes the batch exit 1. Existing output directories are rejected.

For input pinning, add a `sha256` object to each dataset entry containing all consumed input names and their lowercase SHA-256 values (`corpus.jsonl`, `queries.jsonl`, and `qrels.jsonl` or `qrels/test.tsv`). Partial pins and mismatches fail. Files are checked for changes during loading and after every repetition. Hashes establish local integrity, not trusted dataset provenance. This remains a BM25 reference workflow; routing calibration and full-cascade public evaluation are not performed by this command.


## SWE cascade and context-budget sweeps

Compare the actual Compass modes on one explicit clean SWE-Explore snapshot:

```powershell
python -m compass benchmark swe-sweep --dataset D:/datasets/swe.jsonl --instance INSTANCE_ID --repository-id OWNER/REPOSITORY --repo D:/snapshots/project --issue-map D:/datasets/issues.json --commit-map D:/datasets/commits.json --output-dir .keel/swe-sweep-001 --modes t0 t1 t2 adaptive --line-budgets 100 300 600 --repeats 3 --seed 42 --model YOUR_OLLAMA_CHAT_MODEL
```

Build the snapshot index first, as shown above. Store outputs under `.keel` or outside the snapshot so reports do not become untracked source inputs. Omit maps when the record includes issue text and the base commit. `--routing` accepts the same routing JSON as `retrieve`; the sweep does not fit thresholds against its evaluation labels.

Every mode/context-budget configuration receives its own fresh tool/model/token/time budget. Configure these with `--max-tool-calls`, `--max-model-calls`, `--max-tokens`, and `--max-wallclock`; limits apply per run, not to the entire sweep. Configuration order is shuffled reproducibly within each round. Repetitions reuse the same index and have uncontrolled model/OS caches. They do not establish statistical significance or independent task coverage.

Outputs are `runs.jsonl` (incremental evidence), `events.jsonl` (model replies, observations and retrieval events tagged by mode/budget/repetition), `sweep.json`, `comparison.csv`, and `report.md`. Metrics keep SWE's region granularity: line recall/precision/F1, core-file hit rate, and context efficiency. Costs include retrieval seconds, emitted lines, chat tokens, tool/model calls, and vector queries. JSON includes separate nondominated configurations for every quality/cost pair, routing settings, index identity, implementation hashes, model name, and limits.

T2 sends Ollama a dynamic JSON schema containing the currently visible symbol IDs. Other model adapters retain the plain completion interface and receive the same action schema in the prompt. Local action validation remains mandatory. The final available turn requests an explicit `final` selection, which may be empty; a missing or invalid final response still produces `step_limit`. Invalid-action traces retain the validation error. No additional retry calls bypass the configured turn, token or time budgets.

Action schemas are per-call instructions and do not accumulate in conversation history. Structured adapters receive them through response-format configuration; plain adapters receive one current prompt schema. Preflight counts schema bytes in its conservative input upper bound and logs that estimate separately from consumed tokens. Query observations contain the additional terms and new evidence; the original issue stays in the initial message and in the executed search query. Input preflight can reject a call before its tokens are consumed, so a budget failure can occur with low reported usage.

The public runner now defaults to `--evidence-policy read`: T2 sees the bounded candidate catalog and must read a nonempty code page before selecting that symbol. Its final selection can contain only read IDs. When the visible-node limit is full, query/graph actions that cannot add evidence are unavailable. Each decision receives the original issue, current catalog, read pages (1,000 characters each), and action trace; full transcript accumulation is avoided. The final turn narrows the catalog to read candidates. Empty final selections remain possible and do not establish retrieval quality. The core `Routing()` default remains `preview` for compatibility; use `--evidence-policy preview` to reproduce earlier public-runner behavior.

The public runner explicitly requests an 8,192-token chat context (`--chat-context`, PowerShell `-ChatContext`) with a token compute batch of 32. Query embedding requests and explicitly configured chat contexts release their model after each request to reduce resident memory on small machines; this can increase cold-load latency. Index-building embeddings retain normal residency. Reports retain chat context and runtime policy. The optional code-aware ranking prioritizes candidates containing explicit `file.py:line` references from the query; it does not access arbitrary query paths or use gold annotations. Existing result directories retain their original policies and must not be silently merged with new results.

RRF remains the default ranking policy. An experimental `code-aware` policy reweights fused candidates using capitalized/backtick query terms that match candidate identities, identifier coverage, and length-normalized code coverage. Simple plural variants are included; this is a heuristic, not a learned reranker. Ranking evidence is recorded in candidate events, and the policy is stored in routing settings. It changes neither the standalone CORE BM25 reference nor T0 exact lookup. Use `--routing examples/code_aware_routing.json` with `swe-sweep`, or `-Ranking code-aware` with the public runner. Keep policies separate when comparing or calibrating results; development-instance gains require held-out validation.

The public runner supports paired ranking evaluation across a frozen repository sample:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\examples\run_swe_public.ps1 -Repositories 3 -CompareRankings -Repeats 3
```

This selects one seeded eligible instance from each of Flask, Requests and Seaborn, then runs both policies across all four modes (72 retrieval runs). `-PlanOnly -Offline` writes the sample and reports cached snapshot existence without Git/model calls or claiming verified snapshots. `-InstancesPerRepository N` selects N distinct seeded instances in each selected repository; insufficient groups fail before evaluation, without silently shrinking the sample. Selection uses metadata and eligibility checks, never retrieval outcomes. Cached compatible fresh semantic indexes are reused; mismatched settings rebuild the index.

Paired runs alternate policy order across instances and retain separate sweep directories. `comparison.json` and `comparison.md` report equally weighted instance quality/cost means and code-aware-minus-RRF quality deltas per mode, using only instances where both policy configurations completed all repetitions. A separate escalation section compares T2/adaptive against T1 on exactly the same completed instances within each ranking policy, reporting quality and cost deltas. Its denominator can differ from the ranking comparison; excluded IDs remain explicit. Repetitions do not increase task coverage. One instance failure is persisted to `instances.jsonl` and does not prevent later instances from running. Any failed/incomplete instance makes the runner exit 1. These are exploratory reference comparisons; shuffled runs and alternating policy order do not control OS/model caches or establish statistical significance.

Saved results can be summarized without model calls or retrieval:

```powershell
python -m compass.comparison --result .keel/swe-public/RUN_ID/result.json --output-dir .keel/swe-public/RUN_ID/analysis
```

Replace `RUN_ID` with the printed artifact identifier. The export preserves a source-result SHA-256 and the original batch completion flag, reports per-metric improved/tied/regressed task counts, and refuses to overwrite an existing output directory. Its Markdown report includes recall, precision, file hit rate and costs; deltas are descriptive, not a calibrated upgrade rule.

Context budgets can also be replayed against saved candidate ranges without new model or embedding calls:

```powershell
python -m compass.budget_ablation --result .keel/swe-public/RUN_ID/result.json --output-dir .keel/swe-public/RUN_ID/budget-analysis --line-budgets 100 300 500 --symbol-line-caps 32 64
```

This factorial replay fixes retrieval rankings and model selections, varying only packing. Source configurations must have completed all repetitions; exclusions and input hashes remain explicit. It reports emitted-line utilization and a line-count-only recall ceiling, plus the fraction of that ceiling attained. That ceiling can be unattainable with available symbol prefixes. Repetitions are averaged within tasks before task means. Source sweeps must contain a single original line budget to avoid counting configurations as extra tasks. Replay does not measure new retrieval latency, model behavior with larger prompts, or downstream coding performance. Existing output directories are rejected.

To validate the candidate 300/64 configuration on new issues in Requests and Seaborn:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\examples\run_swe_independent.ps1
```

This workflow excludes every instance in `docs/evaluations/compass-final-policy-three-repo.json` before seeded sampling, records the exclusion-source hash, prepares exact snapshots, and runs code-aware retrieval with 300 total lines and a 64-line symbol cap. On success it replays 100/300-line budgets and 32/64-line caps on the saved rankings. Outputs are under `.keel/swe-independent/<run-id>/`, including `budget-analysis/budget-replay.md`. These are new issues in previously used repositories, not held-out repositories. `-PlanOnly -Offline` freezes the sample without Git/model calls; `-PrepareOnly` downloads snapshots without models. Missing eligible instances fail instead of falling back to old issues. Preparation/evaluation failure returns a nonzero exit and skips replay; existing compatible indexes are reused. The Python wrapper also accepts `--previous-result` for a different declared exclusion file.

The underlying public runner, `benchmark swe`, and `benchmark swe-sweep` accept `--symbol-line-cap`; the PowerShell public runner accepts `-SymbolLineCap`. Defaults remain 100/32 in the public runner. Sweep metadata records the cap, and calibration rejects mixing different caps in one protocol.

Deferred upgrades (including missing chat models), step-limited exploration, incomplete indexes, and failed runs make their entire configuration ineligible for frontiers. Errors retain consumed budget evidence and allow other configurations to run. Any ineligible configuration makes the CLI exit 1; existing output directories are rejected. Without `--model`, T0/T1 can be measured, while requested T2 or adaptive upgrades are recorded as deferred. Failed/deferred run records may still contain partial retrieval evidence, but it is excluded from eligible quality/cost means.

This command compares the real cascade implementation with fixed context budgets. It is a single-instance reference experiment, not a full public-data evaluation, an official SWE-Explore score, or routing calibration. Scripted-model tests validate execution and accounting only; they do not establish live-model retrieval quality.


## Repository-held-out routing calibration

`calibrate` selects the four T1-to-T2 thresholds from completed paired SWE sweeps. Collect T0, T1, and T2 runs at the same line budget for instances from **at least three repositories**, supplying `--repository-id owner/repository` to `swe-sweep`. Repository IDs are case-normalized; do not substitute commit IDs, checkout paths, or instance IDs. The current collector requires explicit GitHub-style owner/repository identities without a `.git` suffix.

```powershell
python -m compass calibrate --sweeps .keel/sweep-a/sweep.json .keel/sweep-b/sweep.json .keel/sweep-c/sweep.json --line-budget 300 --seed 42 --holdout-fraction 0.25 --upgrade-penalty 0.02 --output-dir .keel/calibration-001
```

The command hashes seed/repository identity to split entire repositories into development and holdout groups. It searches up to 4,096 grid combinations using development results only, then evaluates the chosen settings on the holdout. Default utility is repository-mean line recall minus `0.02 * repository-mean upgrade rate`. `--max-upgrade-rate` caps the development upgrade rate; it does not guarantee the same rate on unseen repositories. Declare the seed, penalty, grid, line budget, and repository sample before examining holdout results. Repeatedly selecting experiments based on the holdout invalidates its role as an independent evaluation set; the tool cannot police that history.

Each sample averages repeated runs within one instance. T0 exact-hit bypasses are preserved; remaining cases choose the measured T1 or T2 outcome using the **same gate function as online retrieval**. T2 costs already include its T1 prefix, so that prefix is not charged twice. Candidate selection uses repository means so a repository with many issues does not dominate the objective. Reported costs are query means. Each instance must use one index generation across its paired runs. Embedding configuration/dimension, chat-model identity, parser, per-run limits, and exploration settings must match across input sweeps. Failed, deferred, incomplete, missing, or duplicated pairs are rejected. Repeated instances and changing T1 signals are rejected as well.

Outputs are `calibration.json` (input and implementation hashes, grid candidates, split identities, selected settings, simulated decisions, costs, and development/holdout metrics) and `routing.json` (accepted by `retrieve` and `swe-sweep --routing`). Existing output directories are rejected. A custom `--grid` JSON must supply lists for exactly `min_relevance`, `min_overlap`, `max_entropy`, and `max_files`.

This is offline outcome replay, not a new adaptive run, a calibrated probability, or completed real-model validation. Hash embeddings and scripted-model fixtures are suitable only for testing the workflow. Use a real semantic embedding index and chat model for the intended experiment; then run fresh adaptive sweeps using the exported routing settings to measure actual behavior. `public_benchmark_verified` and `online_adaptive_verified` remain false in calibration reports. CORE's document-only BM25 baseline is not used as if it contained T1/T2 traces or region-level supervision.


Local GGUF imports named `keel-embed` and `keel-chat` have passed a real semantic-index/T2 integration smoke check; see [the local model integration note](docs/evaluations/local-model-integration.md). This synthetic check does not establish public-data cascade quality or calibrated routing.


## Prepare the first real SWE cascade experiment

On Windows, with Git, curl, tree-sitter, PyArrow, and the imported Ollama models available:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\examples\run_swe_public.ps1
```

The default prepares **one instance from one repository**, builds a semantic index using `keel-embed`, and evaluates T0/T1/T2/adaptive with `keel-chat`, a 100-line context budget, and one repetition. It is a hardware/integration first pass. It does not provide enough repository groups for calibration. Use `-Repositories 3 -LineBudget 300 -Repeats 3` only after this first pass succeeds. `-PrepareOnly` skips model calls and indexing; `-Offline` requires both downloaded data and verified Git snapshots to exist. The active environment's Python is used, or specify `-PythonCommand` explicitly.

Data comes from the [released SWE-Explore dataset](https://huggingface.co/datasets/SWE-Explore-Bench/SWE-Explore-Bench) intersected by instance ID with [SWE-bench Verified](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified). The upstream [commit-map utility](https://github.com/Qiushao-E/SWE-Explore-Bench/blob/main/build_commit_map.py) also uses Verified as one source of base-commit metadata. Our first preparation path intentionally excludes unmatched/rebench instances. It supplements missing issue text and base commits from Verified, rejects conflicting supplied values, and preserves all core/optional labels, including non-Python files.

On the first download, Hub metadata resolves each dataset to a full commit SHA. Subsequent data downloads use that immutable revision. Metadata and file receipts are cached with local hashes; these are integrity checks, not independent origin authentication. Standard JSONL or Parquet split files are discovered automatically without executing remote dataset-loader code. Ambiguous layouts fail with file names and can be resolved using Python runner options `--swe-files` and `--verified-files`.

Eligibility and selection are explicit in `plan.json`: Verified intersection, available labels with at least one Python core file, issue text within the current 8,000-character query limit, one seeded instance per repository. A predeclared preference for small repositories (Flask, Requests, Seaborn, Pytest, Xarray) makes the first local experiment manageable. No retrieval scores influence selection. The plan is written before checkout, model calls, and quality measurement; this convenience sample is not representative of the full benchmark.

Snapshots are shallow-fetched from canonical GitHub repositories at the exact labeled commit. Existing snapshots must match HEAD and pass clean-input checks. Interrupted managed staging directories can retry a fetch; unrelated staging paths are not overwritten. Checkout preserves LF source content. No target-repository test suite, package installation, or source code is executed. The first semantic index uses exact SQLite vector search to avoid native-storage variables; real LanceDB storage has a separate integration check.

Artifacts live under `.keel/swe-public/<run_id>/`: source/selection plan, model inventory when evaluating, extracted enriched instance JSONL, heartbeat progress, per-instance sweeps, and final results or `failure.json`. Caches are in `.keel/datasets/swe/`; snapshots are in `.keel/swe-snapshots/`. An incomplete/deferred sweep exits nonzero while retaining evidence. Each retrieval run has an independent limit of 300 seconds, 30,000 tokens, four model calls, and 100 tool calls. Index construction and the overall preparation process have no aggregate budget. Model names/digests should be frozen across subsequent experiments.

Python entry point (also exposes explicit repository allowlists and custom model names/endpoints):

```powershell
python -u examples/run_swe_public.py --repositories 1 --repository-id pallets/flask --embedding-model keel-embed --chat-model keel-chat
```

Local tests simulate network transfer and exercise real Git checkout/identity/cleanliness checks. They do not establish that the live Hub export or GitHub transport is reachable. Public-data cascade scores remain unverified until an actual preparation/evaluation run succeeds.


### Windows native-parser and embedding memory handling

A native access violation was reproduced while parsing the real Flask `src/flask/app.py` with tree-sitter 0.26.0. The parser now keeps the syntax tree alive, traverses with a cursor rather than parent/child Node caches, and derives line numbers from byte offsets instead of temporary Point wrappers. The same Flask snapshot subsequently parsed all 80 Python files and 1,570 symbols without the native fault; symbol identities, calls and imports matched the AST extraction. Tree-sitter may retain trailing comments or decorator boundaries differently from AST, so byte-for-byte backend equivalence is not claimed for every chunk.

The optional native parser regression runs a generated 180-method class repeatedly under aggressive garbage collection in an isolated subprocess. A native failure then fails the test rather than terminating the entire test runner. The SWE PowerShell entry point also enables Python's fault handler so a future native crash prints diagnostic stacks instead of disappearing behind the last heartbeat.

The first real index retry also encountered a distinct Ollama embedding buffer-allocation failure (HTTP 500). The SWE runner now explicitly sets token compute `num_batch=32`; override it with `-EmbeddingNumBatch` or Python `--embedding-num-batch`. This is separate from the number of documents per HTTP request. The setting is retained in index embedding metadata and restored for subsequent queries/updates. Oversized inputs still fail because truncation remains disabled. Small-batch probes passed, but this setting is not a guarantee that every model/context fits available memory. Embedding HTTP errors include a bounded server error message when available.

### Local agent tool gateway

Agent sessions use `keel.gateway.ToolGateway` for tool discovery and dispatch.
The gateway checks the role allowlist, exact argument fields and types, declared
write targets, and session-scoped evidence visibility before executing a tool.
Workspace operations retain budget charging; the gateway adds no duplicate charge.
Every attempt emits correlated `gateway_call_started` / `gateway_call_finished`
events with status, duration, and exception type. Argument values and returned
source text are omitted from these gateway events.

This is the local gateway foundation for W6-7. External MCP stdio tools can now be configured as described below.
Local OTLP trace export is available as described below; live container isolation validation remains separate work.

### External MCP tools (stdio)

Install `python -m pip install -e ".[mcp]"` in the interpreter running Keel.
Add an explicit server and tool allowlist to an agent task configuration:

```json
{
  "mcp_servers": {
    "repo": {
      "command": "D:/keel/.venv/Scripts/python.exe",
      "args": ["-m", "compass", "serve", "--repo", "D:/path/to/disposable-repo"],
      "timeout": 30,
      "tools": {
        "find_symbol": {
          "roles": ["scout", "planner", "implementer"],
          "description": "{\"name\": \"exact Python symbol\"} -> matching symbols"
        }
      }
    }
  }
}
```

Replace the executable and repository paths with your actual paths. The model sees
`mcp__repo__find_symbol`; it cannot add servers, tools, or role permissions.
Each call opens an official SDK session, initializes, discovers and validates the
allowlisted tool's input schema, calls it, then closes the session and process.
Session startup is included in latency. One external request consumes one shared
tool call, including failed requests; the timeout is bounded by remaining run time.
Internal server tools and model usage are not visible to Keel's budget accounting.

Successful content and structured results enter the role's evidence ledger, with
a 4000-character preview and explicit recall. Server tool errors become failed
observations. Gateway events record correlation, transport, status and duration;
server stderr is saved beside the run trace as `mcp-<server>.stderr.log`.
The 1 MB result limit is checked after SDK decoding, not a transport memory limit.

Only configure trusted server executables: stdio subprocesses run with host
permissions, with the workspace as their working directory. Tool allowlists and
server read-only annotations do not provide operating-system isolation. The run's
declared-file audit still applies to repository changes. This client currently
supports stdio, not remote HTTP transports, sampling, or elicitation.

Validate the client against the actual Compass subprocess with:

```powershell
python -m unittest discover -s tests -p test_mcp_client.py -v
```

### Local OpenTelemetry trace export

Every Keel run now writes `spans.otlp.json`: one compact OTLP/JSON
ExportTraceServiceRequest record, containing a run span, child role spans, and
model, agent gateway tool, and verification command spans. No additional package
or running Collector is required. `trace.jsonl` includes matching `trace_id`,
`span_id`, and `trace_flags` fields; `result.json` reports export status and path.
Span timestamps use an epoch anchor plus a monotonic clock. Interrupted calls
close with ERROR status when their role ends, including unexpected exceptions.
Export-file failures are reported in `result.telemetry` without replacing the
actual task outcome.

The OTLP file includes allowlisted operational metadata, not goals, prompts,
source text, command arguments, or server error payloads. Existing trace and ledger
artifacts retain their original evidence content. This is a local file exporter,
not an OpenTelemetry SDK integration: Collector upload, remote context propagation,
and server-internal spans are not implemented. Direct Workspace operations outside
the agent gateway retain their existing events rather than measured tool spans.
Hard process termination can prevent the final OTLP file from being written;
the append-only event trace remains available.

The encoding follows the [OTLP JSON specification](https://opentelemetry.io/docs/specs/otlp/)
and [OTLP file format](https://opentelemetry.io/docs/specs/otel/protocol/file-exporter/).
The local file has not yet been validated against a live Collector.

```powershell
python -m unittest discover -s tests -p test_telemetry.py -v
python examples/demo.py
```

### Live Keel agent and verifier sandbox checks

Run the installed Ollama chat model against a disposable, persistent fixture:

```powershell
python examples/run_keel_agent.py
```

The script saves the repository, task config, runtime artifacts and `summary.json`
under `.keel/agent-smoke/<id>`. A heartbeat reports the last active role/event.
It checks the exact expected source change, preserved greeting behavior,
independent acceptance, declared-file audit, actual model calls, and OTLP export.
Failures return nonzero and keep all evidence. This single synthetic smoke task
is not an UpgradeBench score or evidence of general upgrade success.

Agent settings now accept optional `require_evidence: true`: Scout and Implementer
must obtain a successful evidence result before a final answer is accepted.
Planner receives explicit impact evidence and is exempt. Default remains false.
When the model supports structured output, role-specific final contracts and
available tool names constrain the response; the last turn requests a final only
once the evidence gate is satisfied. Model configuration accepts `num_ctx`;
this smoke script uses 8192 and caps the plan at one work item with
`agent.max_work_items` (default 20). The cap is enforced before implementation. Independent verification remains authoritative even
when the model claims success. Recall rejects offsets beyond stored evidence.

With Docker Desktop running and a local Linux Python image available:

```powershell
docker pull python:3.11-slim
python examples/verify_keel_sandbox.py
python examples/run_keel_agent.py --backend docker --image python:3.11-slim
```

The sandbox probe does not pull images. It checks real container UID, effective
capabilities, no-new-privileges, read-only root/workspace mount flags and denied
writes, writable temporary storage, absence of non-loopback IPv4 routes, and
unchanged host fixture. Results persist under `.keel/sandbox-probes/<id>`.
Missing Docker, missing images, daemon errors and failed checks return nonzero;
there is no local fallback. These checks cover the verifier container only;
Agent execution and MCP processes still run on the host. Live resource exhaustion,
IPv6 connectivity and complete escape resistance are outside this probe's scope.

If Ollama reports CUDA out-of-memory, request CPU-only inference explicitly:

```powershell
python examples/run_keel_agent.py --backend docker --cpu
```

This sends `options.num_gpu=0` on every model request and records `cpu_requested`
in the summary and `num_gpu` in the task configuration. CPU inference uses host
RAM and can be slower; its default wall-clock budget is 900 seconds (GPU/default
remains 300). Override with `--max-seconds`. The verifier still runs in Docker.
No automatic device fallback or change to acceptance checks is performed.
A bounded live CPU model request returned valid JSON on 2026-10-15; the complete
CPU-plus-Docker smoke run is still pending. The earlier real Docker isolation
probe passed on the user's machine.

### W8 ledger and local tool memoization

Local `list_files` and literal `search_code` observations now reuse ledger-backed
results keyed by tool arguments, repository root, and the full visible workspace
content fingerprint. File reads retain their existing content-addressed cache.
An add/edit/delete invalidates the affected observation key. The workspace is
fingerprinted before and after a lookup/scan; detected changes reject the result
rather than publish mixed-snapshot evidence. This check cannot detect an ABA
change that is completely reverted between fingerprints.

Every invocation, including a hit, consumes its normal tool budget. Hashing still
reads workspace bytes; savings are repeated text scanning/serialization work,
not a proven latency or model-token reduction. Compass retrieval, external MCP,
verification and writes are not memoized by this new cache. Persisted results
can be reused only with the same ledger and matching repository identity.
`result.memory` reports cache entries, hit lookups, and fact count; `tool_cache`
events expose per-operation hits and repetition count.

Each agent session still gets its own evidence fact IDs even when cached payloads
are reused. Trusted host orchestration can explicitly call
`target.gateway.accept_evidence(source.gateway, selected_fact_ids)` to grant up to
16 selected file/symbol facts from the same Workspace. The copied evidence has a
new recipient-owned ID and a traced source reference. It is a historical
observation, not a freshness guarantee. This host API is not a model tool and
is applied at role boundaries only when `context_handoff` is enabled. Decision
history, failed attempts and verification records cannot be shared through it.

Run the saved, model-free integration demonstration:

```powershell
python examples/memory_demo.py
python -m unittest discover -s tests -p test_memory.py -v
```

Artifacts persist under `.keel/memory-demo/<id>`. W8 includes bounded file-read selection at role boundaries; larger-workload
overhead and model-cost measurements remain outstanding.

### Opt-in context handoff at role boundaries

Set top-level `"context_handoff": true` in an agent task configuration, or run:

```powershell
python examples/run_keel_agent.py --backend docker --cpu --context-handoff
```

The host selects Scout file-read evidence matching the impact file list for the
Planner. Before each Implementer session, it selects Scout/Planner file reads
matching only that work item's declared files. Each selection is limited to four
facts and one fact per canonical path, with recent Planner observations preferred.
Source bytes must match the recorded SHA-256 at selection; stale or deleted
files are skipped. The model receives recipient-owned fact IDs, bounded previews,
source IDs, paths and hashes in `task.evidence`. Existing token preflight includes
these previews. No role history, model decisions, file listings, search/MCP results
or arbitrary ledger IDs are automatically transferred.

The original source IDs confer no recall permission. Selected copies remain
historical observations: source matching is a check at selection time, not a lock
against subsequent external changes. Implementers should inspect current source;
write scoping, static auditing and independent verification remain authoritative.
Transferred facts do not satisfy the optional `require_evidence` gate: Scout and
Implementer must obtain an observation through a tool in their own session.
Earlier Implementer histories are not shared with later work items; initial
Scout/Planner evidence is rechecked at every boundary. `result.memory` includes
`handed_off_facts`, and trace events record `context_selected` and `evidence_handoff`.

The default is false, preserving existing isolated sessions. The new role-boundary
behavior has been tested with scripted agents; a live CPU/Docker run with handoff
enabled is a separate validation from the previous no-handoff smoke result.

For CPU host-memory pressure, the smoke runner accepts `--num-ctx 4096` to reduce
context/cache allocation (default remains 8192). The selected context is recorded
in task.json. This cannot replace adequate free host RAM; WSL swap does not serve
as Windows-native Ollama's paging file. A context-handoff attempt on 2026-10-15
failed before handoff with `std::bad_alloc`; its Ollama log reported only 525.9 MiB
free host RAM. No model/handoff correctness failure is inferred from that request.

```powershell
python examples/run_keel_agent.py --backend docker --cpu --context-handoff --num-ctx 4096
```

### Controlled memoization measurement

Set top-level `"memoization": false` to bypass local read/list/literal-search cache
lookup and insertion; default is true. The same permission checks, budgets, source
fingerprint guards, and output semantics remain active. Compass and MCP behavior
is unaffected. `result.memory.tools` reports requests, hits and computations per
supported tool, while snapshot_calls/snapshot_bytes expose hashing work.
Computations count decode/list/scan invocations, including a miss that later fails;
they are not counts of physical disk reads. A read hit still reads source bytes.

Run a paired, model-free experiment with alternating mode order, fresh ledgers,
fixed workloads and a source edit between two phases:

```powershell
python -m keel.memory_benchmark
```

It saves JSON, Markdown, traces and fixture repositories under
`.keel/memory-bench/<id>`. CLI options include `--files`, `--lines`, `--repeats`,
`--trials` and `--output-dir` (must not exist). Timing includes fingerprints, cache
I/O, budget and trace costs, but not Agent model calls, gateway previews or task
success measurement. Both modes keep fingerprint guards, so this isolates cache
reuse, not removal of snapshot correctness checks. OS caches are uncontrolled.
Results are checked for matching semantic observations and final source bytes.

The initial 64-file synthetic run found 31 requests in both modes, computations
31 -> 6 and 25 hits, but median elapsed time 0.749s -> 0.799s (6.7% slower).
A separate 256-file fixture measured 3.256s -> 2.955s (9.2% faster), with
identical outputs and request counts. Neither result establishes token savings,
fewer model requests, or general speedup.
See [the W8 measurement note](docs/evaluations/keel-memory-measurement.md).

### Optional LangGraph orchestrator (initial adapter)

The default remains `"orchestrator": "native"`. Install the optional framework:

```powershell
python -m pip install -e ".[langgraph]"
python -m unittest discover -s tests -p test_orchestration.py -v
```

Select `"orchestrator": "langgraph"` in a task, or use
`examples/run_keel_agent.py --orchestrator langgraph`. The adapter resides in
`keel/adapters/langgraph/`; both drivers execute the same Scout, Planner,
Implementer, Verifier, Auditor and Critic phase functions. Scout inspection and
Planner generation are separate graph nodes. Baseline verification remains a
Scout-stage prerequisite with its existing distinct role phase. Work items remain
sequential. Expected failures route to Critic once, preserving shared permissions,
ledger, evidence handoff, audit, mutation, budget, trace and patch generation.

StateGraph uses SqliteSaver to save node progress, ledger path and budget snapshots
under `checkpoints.sqlite`, keyed by the run directory name. It does not store full
conversation histories, source bytes, model objects or Workspace handles in graph
state. `result.orchestration` records the chosen engine, visited/completed node
callbacks and checkpoint information. The ledger connection permits sequential
node callbacks from framework worker threads; concurrent node execution is not
supported. Each run has independent ledger and checkpoint databases.

**Checkpoint inspection is not durable task recovery.** Runtime resources and
budget clock still live in-process, and external edits/verification have side
effects. This adapter supports only guarded same-process approval interruption/resume,
described below. It offers no time-travel, automatic retries or cross-process recovery. Reopening a checkpoint
alone cannot safely resume Keel. Missing dependencies fail before output directory
creation or repository edits; no silent native fallback is performed.

The initial adapter was written against the official
[StateGraph compile](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/compile)
and [SqliteSaver](https://reference.langchain.com/python/langgraph.checkpoint.sqlite/SqliteSaver)
contracts. Initial package installation failed in the restricted environment. The user
subsequently installed the extra and reported all five initial adapter tests passing;
the installed virtual environment has now also passed the expanded approval suite. Native regression validation and the framework-independent
failure-routing tests are separate evidence.

### Guarded LangGraph write approval

For LangGraph task configs, enable `"approval_before_write": true` and supply an
explicit trusted-host callback via `run(..., approval=callback)`. The callback
receives the validated plan hash, workspace hash, declared file list, ledger path
and current budget, and must return exactly a boolean. CLI users may select:

```powershell
python -m keel run your-langgraph-task.json --repo D:/path/to/disposable-repo --interactive-approval
```

The task must select `"orchestrator": "langgraph"`. CLI request/prompt text goes
to stderr and EOF denies. No callback is supplied implicitly to approve writes.
The model cannot supply an approval callback or expand permissions through it.

A separate side-effect-free graph node interrupts between Planner and Implementer.
The same process retains runtime state and resumes with `Command(resume=...)`.
Only the approval node restarts; earlier role calls, budget charges and plan
validation are not replayed. Before continuing, the runtime rechecks budget,
configuration/plan hashes, full workspace bytes, write paths and hard links.
Denied, malformed or invalidated decisions route to Critic without planned edits.
The original wall-clock budget includes approval wait; an expired budget refuses
continuation. A blocking host callback/input is not forcibly timed out.

Trace records `approval_requested`, `approval_decided`, `approval_resumed` or
`approval_invalidated`. `result.approval` distinguishes decision and invalidation.
`orchestration.resumable` remains false to indicate no cross-process recovery;
`resume_scope` explicitly describes the same-process-only behavior. Killing this
process and reopening its checkpoint is still unsupported. This is write approval,
not temporary privilege escalation or a generic shell permission system.

Try a disposable, model-free demonstration:

```powershell
python examples/langgraph_approval_demo.py
python -m unittest discover -s tests -p test_orchestration.py -v
```

The demo supports `--decision approve` / `--decision deny` for scripted host tests
and saves fixtures, checkpoints, ledger, trace, patch and summary under
`.keel/approval-demo/<id>`. Denial returns nonzero.

### W9 UpgradeBench candidate intake

Collect a bounded set of merged upgrade/bump/migration PR metadata from an explicit
repository (read-only GitHub requests; no repository code execution):

```powershell
python examples/mine_upgradebench.py --repository psf/requests --limit 3 --pages 1
```

For targeted discovery, add `--discovery search --query compatibility` (also
`migration` or `upgrade`). Search mode skips PRs without source changes before
commit/tree downloads and records discovery exclusions separately. Use
`--resume-from <artifact-directory>` to reuse verified responses and fetch missing
routes into a new run. Transport failures get at most three attempts; HTTP limits
stop immediately. Keep the same discovery arguments when continuing a run.

`--limit` caps collected PR records at 1..20; `--pages` caps recent closed-PR listing
pages at 1..3. Each listing page has up to 100 PRs. Title-only selection is heuristic
and may produce zero eligible candidates. Optional `GITHUB_TOKEN` is read from the
environment for API access, never written to receipts or passed in subprocess args.
Raw API responses and hashes are archived under `.keel/upgradebench-mining/<id>`;
network/rate-limit/incomplete-data errors return nonzero and preserve completed
candidates in a partial screening report. `--replay-from <artifact-directory>`
recovers hash-verified cached responses offline. These archives are curator-only,
not agent context.

Screening requires a merged PR, title signal, at least three changed files,
a dependency manifest change, non-test source change and CI evidence. Snapshot
revisions use the merged commit and its first parent, not a mutable PR base field.
PR file lists are count-checked; truncated CI tree responses fail closed. Raw PR
file metadata is not yet verified against the exact merged Git diff.
Tooling title signals and workflow-only changes are classified separately from
provisional main-track candidates. Structural eligibility alone does not establish
a runtime compatibility fix; `triage` reports tooling and main-track counts.
An independent compatibility review queue retains small source migrations that
fail only the file-count/manifest requirements. Every entry needs manual review
and base/gold reproduction; strict eligibility and ready-task counts stay separate.

For an existing local candidate export, use:

```powershell
python -m keel.upgradebench --input D:/path/to/candidates.json
```

Reports retain rejection reasons, canonical identities, frozen SHAs, input/manifest
hashes and a seeded pending 10% manual-review sample. No candidate is marked
`benchmark_ready`: reproducible images, shared base/gold acceptance, valid baseline
failure, description leakage checks and review are still pending. No benchmark
score or validated real-task count exists yet. This is a conservative first slice
that requires dependency-file changes, and can miss runtime-only migrations.
See [the UpgradeBench intake contract](docs/upgradebench.md).

The first curator compatibility probe is available as
`python examples/reproduce_starlette_1936.py --build-image`. It compares clean
base/gold snapshots using one Docker image and two identical API checks under
explicitly selected AnyIO 4.0.0. See [scope and pending evidence](docs/evaluations/upgradebench-starlette-1936-review.md).
Probe success does not mark a task benchmark-ready.
After a successful reproduction, `examples/run_starlette_upgrade_task.py
--reproduction <artifact-directory>` prepares an isolated base export without
Git history or gold source. Add `--execute` for the real CPU Ollama repair and
Docker acceptance. Curator evidence stays outside the agent workspace; the
agent process itself still runs on the host.
