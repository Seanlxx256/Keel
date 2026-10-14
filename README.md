# Keel

A reliability runtime for long-horizon coding tasks.

Keel is a governance layer around coding-agent execution. It targets runtime failures such as wasted retries, timeouts, premature completion, and misleading validation. The goal is to measure improvements under a fixed model and budget.

Compass, the planned adaptive repository-retrieval MCP server, will provide repository intelligence. The design also calls for an early-stopping predictor and isolated concurrent workspaces. Those components are not implemented yet.

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
- Implement Compass AST indexing, hybrid retrieval, evidence-based escalation, and MCP integration.
- Add isolated concurrent workspaces, bounded Critic retries, and richer context management.
- Export OpenTelemetry spans, collect labeled trajectories, and train the early-stopping predictor.
- Run public benchmarks and controlled ablations under fixed models and budgets.

No benchmark improvements or production reliability claims are reported yet.
