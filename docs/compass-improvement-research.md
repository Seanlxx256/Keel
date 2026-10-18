# Compass original-goal improvements

Research and implementation review: 2026-10-18. The original objective remains an
adaptive code-context service: T0 precise identity/location, T1 hybrid retrieval,
T2 bounded inspection/graph exploration. This increment does not replace that
architecture or narrow Compass to a file-search helper.

## Findings from local code and evaluations

- RepositoryIndex.find_symbol/context returned full symbol code and embedding text.
  The service lacked a compact file outline, despite already storing parent IDs and
  definition ranges. Agents had to request more source than needed for navigation.
- Retriever.exact accepted whole symbol names and paths, but not file:line locations.
- The three-repository development evaluation found T2 selections discarded useful
  T1 candidates; read-before-select did not prevent this. See
  evaluations/compass-final-policy-three-repo.md. This is not a reason to universally
  prefer any new policy, and the labels are not used to tune new thresholds.
- Indexing is Python-only (source_files accepts .py). Static graph linking does not
  resolve all dynamic calls, inheritance or cross-language references. HashEmbedder
  is a deterministic test facility, not a neural semantic model. Existing Ollama
  embeddings remain available; no new embedding quality claim is made.
- Retrieval routing is heuristic and offline calibration exists; task success alone
  is not a valid relevance label or evidence of online learning.

## GitHub methods reviewed and adoption decisions

| Primary implementation | Relevant method | Compass decision |
| --- | --- | --- |
| [Serena](https://github.com/oraios/serena#retrieval) | Symbol overview, definitions and references through language-server/IDE backends | Add compact static overview using existing indexed parent/range data. Keep Serena as an external provider for richer language analysis; no Serena source copied and no LSP reimplementation. |
| [Aider repository map](https://aider.chat/docs/repomap.html), [repomap.py](https://github.com/Aider-AI/aider/blob/main/aider/repomap.py) | Concise signatures/identities; dependency graph ranking under a context budget | Adopt structure-first navigation and explicit payload budget. Graph PageRank/context packing is a later ablation, not implemented by this increment. |
| [Continue retrieval pipeline](https://github.com/continuedev/continue/blob/main/core/context/retrieval/pipelines/RerankerRetrievalPipeline.ts) | Multiple candidate sources, deduplication, separate reranking and fallback on reranker failure | Preserve a configurable T1 prefix instead of allowing refinement to silently erase every strong seed. This is an experimental policy, not a reproduction of Continue's algorithm. A neural reranker adapter remains future work. The repository currently states it is read-only/unmaintained; inspect the code as a method reference, not a new runtime dependency. |
| [RepoHyper](https://github.com/FSoft-AI4Code/RepoHyper) | Search/expand/rerank over repository semantic graphs with a trained link predictor | Candidate expansion and final selection should be evaluated separately. Do not add a trained GNN without matching training data and independent evaluation; completion results do not prove bug-repair benefits. |
| [Qwen3 Embedding/Reranker](https://github.com/QwenLM/Qwen3-Embedding) | Dedicated embeddings and query-document reranking, with public inference examples | Suitable candidate backend to benchmark against current embeddings/ranking. No weights downloaded or model selected without local resource/quality measurements; not installed in this increment. |

These are inspected primary project sources, not endorsements based on stars or
third-party claims. Links to main are research references, not vendored dependency
pins. Existing Serena runtime installation remains separately isolated.

## Implemented increment

1. RepositoryIndex.overview, Compass MCP get_symbols_overview and `compass overview`:
   parent-aware definition depth, count/byte bounded pages, next_offset, source hash,
   parser status and index identity; no source bodies/docstrings. Empty or partial
   parse state stays explicit. Oversized individual identities fail rather than being
   silently truncated. max_bytes measures default ensure_ascii=False JSON encoding,
   not tokenizer usage or pretty-printed CLI output. Native Keel Compass gateway can
   also call it and archive evidence. This remains static Python structure, not LSP.
2. T0 handles standalone relative file.py:line, file.py:line:column and file.py#Lline,
   choosing the smallest indexed containing definition. A natural-language issue
   merely mentioning a location is not short-circuited to one symbol. Missing matches
   still follow the normal cascade; ambiguous names retain existing behavior.
3. Routing.t2_preserve_top (default 0, historical behavior) optionally reserves a
   bounded T1 prefix before T2-selected rows. Deduplicated rows retain provenance;
   reserved source is not represented as model-read evidence. This prevents dropping
   the configured prefix, not arbitrary recall loss or worse precision. It can crowd
   out useful new results and therefore requires a quality/cost ablation before any
   default change. No budget reset or extra permissions are introduced.

Usage:

```powershell
python -m compass overview --repo D:\keel keel/recovery.py --depth 1 --limit 20 --max-bytes 12000
python -m compass retrieve --repo D:\keel "keel/recovery.py:15" --mode t0
```

The repository index must be current. Rebuild/update using existing commands first;
the new tools retain stale-index rejection. examples/mcp-compass.json explicitly
allows Scout to use overview, search_code, find_symbol and get_context: candidates ->
outline -> chosen source/context. impact_analysis is not authorized by this profile.
The sample MCP server has no chat model configured, so it cannot hide additional
T2 chat calls inside an external request. Native Keel Compass retrieval can use the
existing shared-budget T2 path when explicitly enabled; its policy still needs evaluation.

## Verification and measurement boundaries

tests/test_compass_navigation.py checks complete pagination, hierarchy, byte bounds,
staleness, smallest containing definition with no T1/model call, and reserved-seed
provenance. Existing retrieval, index, MCP and Agent suites are also checked.

examples/measure_compass_navigation.py copies explicit developer-selected Python
files into an isolated snapshot and records source hashes, outline bytes and T0
usage without model calls. Initial artifact .keel/compass-navigation/v1/measurement.json
contains recovery.py (17404 source bytes -> 2923 outline JSON bytes) and retrieval.py
(26084 -> 4315), 32 depth<=1 definitions total and zero model calls. This is a
navigation/payload smoke measurement, not equal-information compression, a retrieval
benchmark or proof of total Agent token savings. Follow-up source reads still cost.

Next independent experiments: native Compass overview versus full-file navigation;
baseline T2 versus reserved-prefix T2 at equal returned-line budgets; then
Compass-only/Serena-only/cooperative retrieval with fixed Keel tasks. Keep original
results and frozen policy versions. Reference patches must not enter retrieval or
experience memory. Broader LSP provider integration, neural reranking, multilingual
indexing and persistent feedback learning remain unimplemented, not implied successes.
