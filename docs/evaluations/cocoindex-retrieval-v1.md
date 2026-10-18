# CocoIndex semantic retrieval adapter

The comparison now accepts `--engines cocoindex_semantic` and an isolated
`--cocoindex-python` interpreter. This adapter executes installed upstream code;
it does not reimplement an embedding model or synthesize search responses.

Upstream interfaces inspected on 2026-10-18:

- [CLI](https://github.com/cocoindex-io/cocoindex-code/blob/main/src/cocoindex_code/cli.py):
  `init --force`, `index`, `search --json --lang python --limit 100`, `daemon stop`.
- [Search schema](https://github.com/cocoindex-io/cocoindex-code/blob/main/src/cocoindex_code/protocol.py):
  `success`, `results`, `file_path`, `start_line`, `end_line`.
- [Configuration](https://github.com/cocoindex-io/cocoindex-code/blob/main/src/cocoindex_code/settings.py):
  isolated `COCOINDEX_CODE_DIR`, local sentence-transformers embeddings.
- [Package extras](https://github.com/cocoindex-io/cocoindex-code/blob/main/pyproject.toml):
  `cocoindex-code[embeddings-local]`; separate venv avoids MCP dependency conflicts.

## Execute

From the project root with the usual Compass-capable Python interpreter:

```powershell
python examples/setup_cocoindex.py --output .keel/tool-checks/cocoindex-evaluation-v2 --source .keel/swe-public/bdb1b28a48574f5fa371d7f53271854e/result.json --timeout 3600
```

This creates/reuses `.keel/tools/cocoindex-venv`, installs CocoIndex and explicitly
installs `sentence-transformers>=3.3.1` in addition to the upstream extra. It
checks actual sentence-transformers and torch imports before any task. It installs local
embedding dependencies, records `pip freeze` and CLI version, and compares the
same three development queries to the historical Compass results. First use
requires downloading packages and embedding weights. A fresh output directory
is required, preserving failed attempts. `--skip-install` reuses installed
packages; it does not skip indexing, queries, or scoring. Model API keys are
not needed for the selected local embedding provider.

For an already installed engine:

```powershell
python examples/compare_retrieval_alternatives.py --source .keel/swe-public/bdb1b28a48574f5fa371d7f53271854e/result.json --output .keel/retrieval-alternatives/cocoindex-v1 --engines cocoindex_semantic --cocoindex-python .keel/tools/cocoindex-venv/Scripts/python.exe
```

## Isolation and protocol

Only tracked files are copied byte-for-byte into disposable task directories.
The original repository and its `.git` metadata are not passed as a writable
project to CocoIndex. Symbolic links and paths outside the snapshot are rejected.
The worker receives query text, source path and execution settings, never labels.
Source manifests, stage logs, raw search JSON and worker results are saved.

Each task has its own CocoIndex settings and daemon state; the embedding download
cache is shared across tasks. Inherited CocoIndex host/path routing overrides
are removed only in the child environment. The worker requests shutdown of its
own daemon on completion/failure. Unconfirmed cleanup is recorded.

Python files are indexed using native upstream chunking. The full issue is
submitted as the semantic query; any model token truncation follows upstream
behavior and is not independently instrumented. Native candidate order is kept,
with the common maximum of 100 unique output lines and 32 lines per chunk.
This is an embedding baseline without a reranker or an agent loop. Chunk and
symbol boundaries differ from Compass; a matched line budget does not make
their corpus segmentation identical. Model weight revision is not independently
pinned; the configured model and resolved package versions are recorded.

There are no generation-model calls. Embedding calls/tokens are not counted as
zero: they are explicitly unmeasured. Missing packages produce `unavailable` and
no relevance metrics; invalid responses/ranges produce failures. Paired summaries
include only tasks where both compared systems have valid measured results.

## Current evidence

The real isolated setup attempt is saved at
`.keel/tool-checks/cocoindex-setup-v1/setup.json`. Venv creation succeeded;
package installation failed with pip reporting no available distribution.
The active restricted environment could not obtain the package; this does not
establish that the package cannot be installed from a normally accessible index.

The actual comparison preflight at
`.keel/retrieval-alternatives/cocoindex-preflight-v1/comparison.json` records all
three CocoIndex tasks as unavailable, with null quality metrics and zero paired
tasks. There is **no CocoIndex quality or speed result yet**. Worker/parser,
snapshot-copy and unavailable-result tests validate the adapter boundaries,
not the unexecuted upstream embedding/indexing path.

The subsequent user-terminal attempt `cocoindex-evaluation-v2` installed
CocoIndex Code 0.2.42 / CocoIndex 1.0.25 successfully, but all three indexes
failed with `No module named 'sentence_transformers'`. Inspection of the actual
venv confirmed the module was absent despite requesting `embeddings-local`.
Pip was 22.3; the specific resolver cause has not been independently proven.
The explicit dependency and import check above address the observed missing
dependency without relying solely on extras or CLI-version checks. This is a
setup fix, not a measured retrieval improvement.

## Completed user-terminal evaluation

`cocoindex-evaluation-v3/comparison/comparison.json` completed all three tasks
with CocoIndex Code 0.2.42 and local Snowflake/snowflake-arctic-embed-xs
embeddings. All disposable-copy integrity checks passed and daemon cleanup
returned zero. Source receipt, per-task query hashes and Compass index references
match the earlier Serena comparison. No source patch or agent repair was tested.

Line recall (%), same tasks and 100-line budget:

| Task | Compass code-aware (historical) | Serena symbol adapter | CocoIndex semantic |
|---|---:|---:|---:|
| Flask 5014 | 3.19 | 10.22 | 4.63 |
| Requests 1724 | 4.62 | 0.00 | 0.43 |
| Seaborn 3069 | 1.67 | 2.06 | 0.00 |
| Macro mean | 3.16 | 4.09 | 1.69 |

CocoIndex mean line precision is 11.67%, versus historical Compass 42.67%
and Serena adapter 48.48%; mean core-file hit rate is 44.44%, versus 72.22%
and 55.56%. Serena emits 90 lines on average; Compass and CocoIndex emit 100.
These are descriptive measurements on three already exposed development tasks,
not significance tests or a claim about other models and repositories.

The measured CocoIndex configuration has native chunks, full-issue embedding,
a small default general embedding model and no reranker. It wins against
Compass on Flask and loses on the other two tasks. This does not evaluate
all semantic retrieval systems or prove that semantic retrieval cannot help.
The first 100-line packing policy also penalizes relevant lower-ranked chunks.
Candidate inspection, matched reranking and new held-out queries are needed
before selecting a production combination. Do not tune defaults to these labels.

Total setup duration was 725.28 seconds, including installation; per-task
worker launch/copy/index/query durations were 72.66, 90.70 and 167.14 seconds.
These are not warm query latencies and cannot establish an online speed ranking.
