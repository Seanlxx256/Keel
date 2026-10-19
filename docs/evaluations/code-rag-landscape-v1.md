# Code retrieval landscape and native comparison protocol

Research date: 2026-10-19. This is a representative shortlist, not a market-share
ranking. Product popularity does not establish retrieval quality. Product agents,
search engines, ranking components and embeddings must not share one leaderboard
without identifying the tested scope.

## Primary-source findings

| System | Verified mechanism / lesson | Reproducible scope here |
|---|---|---|
| [Aider RepoMap](https://aider.chat/docs/repomap.html) | Symbols plus dependency-graph ranking select compact repository context under a token budget. Structural importance differs from lexical similarity. | Native ranked-tag component via installed `aider-chat==0.86.2`; independent AST spans for shared line-budget scoring. Not full Aider or its rendered map. |
| [Continue](https://docs.continue.dev/guides/codebase-documentation-awareness) | Current guidance favors agent exploration/search and MCP. Its legacy codebase provider is explicitly deprecated. | Native TypeScript/IDE pipeline not yet executed. Do not label a Python hybrid imitation as Continue. |
| [Continue source pipeline](https://github.com/continuedev/continue/blob/main/core/context/retrieval/pipelines/NoRerankerRetrievalPipeline.ts) | Combines recent-file, full-text, embedding and repository-map contexts, then deduplicates. Useful lesson: diversify candidate acquisition rather than merely reorder one pool. | Algorithm study only; recent edits and IDE state are absent from frozen issue queries. |
| [Sourcegraph Cody](https://sourcegraph.com/docs/cody/faq) / [Zoekt](https://github.com/sourcegraph/zoekt) | Cody uses search/code intelligence; current enterprise FAQ says embeddings were replaced with Sourcegraph Search. Zoekt is a native trigram search component. | No native deployment measured yet. A SQLite FTS test is not Sourcegraph. |
| [GitHub Copilot](https://docs.github.com/en/copilot/concepts/prompting-and-context/repository-indexing) | Repository indexing supplies context for supported product workflows. | No public identical internal ranker interface verified; not locally replicated or scored. |
| [Cursor](https://docs.cursor.com/account/privacy) | Documents server-side embedding/index metadata behavior. | Closed service; no isolated internal-retriever measurement here. Account-level evaluation would be a separate experiment. |
| [Serena](https://github.com/oraios/serena) | Language-server-backed symbol navigation and references support iterative exploration. | Existing deterministic query adapter is measured, not a full Serena-guided agent. |
| [CocoIndex Code](https://github.com/cocoindex-io/cocoindex-code) | Native code indexing and semantic retrieval. | Existing four-task native results retained. |

## What to learn before modifying Compass

- Separate candidate acquisition, graph expansion, ranking and context packing.
  The present generic reranker loses useful results; a stronger candidate pool is
  a different intervention from a different reranking policy.
- Evaluate code-trained embeddings/rerankers separately from generic text models.
  [CoRNStack](https://arxiv.org/abs/2412.01007) studies code retrieval and reranking,
  including issue localization. Its reported numbers are not Compass comparisons.
- Static single-query retrieval and multi-turn tool search need separate tracks.
  A product with recent editor state or multiple model calls gets more information
  than a query-only retriever; account for those inputs and costs explicitly.

## First native additional control: Aider ranked tags

The adapter calls installed `RepoMap.get_ranked_tags` directly, with no chat
files and identifier/path hints extracted solely from the issue text. It uses
Aider's own parser queries and graph ranking, not Compass symbols or a rewritten
PageRank. The tag cache is in memory to avoid writing into source snapshots.
Python AST maps zero-based native tag positions to full definition ranges;
file-only and unmappable tags are counted rather than assigned fictitious spans.
The common scorer validates ranges and packs 100 lines, at most 32 per region.
This packing differs from Aider's native rendered repo map and is disclosed.

`examples/setup_aider_retrieval.py` creates a project-local isolated environment,
pins Aider, records dependency versions, probes the actual interpreter and invokes
the existing comparison entry point. Installation and evaluation have an overall
deadline and heartbeat logs. No generation API keys or generation calls are used.
Source/query-only worker requests exclude relevance labels. Completed original
Compass runs are read from the source report rather than rebuilt.

```powershell
Set-Location D:\keel
& 'D:/code/monocular_depth_estimation/.venv/Scripts/python.exe' examples/setup_aider_retrieval.py --output .keel/tool-checks/aider-retrieval-user-v1 --source .keel/retrieval-validation/run-v12/source-result.json --timeout 1800
```

Use a new output directory for each attempt. Existing venv installations can be
reused with `--skip-install`; prior failed reports stay intact. This first study
uses the same four exposed tasks as the existing comparison, so it is a diagnostic
component comparison, not held-out generalization or an end-to-end repair score.
Native ranking API compatibility is probed by the actual worker; failures remain
explicit and are not assigned zero recall.

## Follow-up comparison requirements

Freeze new task IDs before measuring additional policies. Keep fixed source
commits, Python corpus, query text, candidate cap and output budget. Report
component results and full-agent results separately. Record actual versions,
implementation hashes, failures, latency and initialization cost; compare only
common successfully measured tasks and preserve the full failure inventory.
Do not substitute a homegrown algorithm for an unavailable native system.

## Executed evidence in this session

The SQLite FTS5 control completed on the same four tasks, using the existing
Compass chunks and tokenizer: mean line recall 0.591%, precision 16.00%,
file hit rate 22.50%. Historical Compass on these tasks has recall 2.624%,
precision 38.25%, file hit rate 43.33%. Artifacts:
`.keel/retrieval-validation/market-lexical-v1/comparison.json`.
This measures a lexical library configuration, not a product-level competitor.

The actual Aider installation attempt is retained at
`.keel/tool-checks/aider-retrieval-v2/setup.json` with `install.log`.
This execution environment has `PIP_NO_INDEX=1`, no cached matching Aider
distribution, and direct PyPI requests fail with WinError 10061. No proxy,
global pip configuration or permissions were changed. Therefore there is no
native Aider metric yet. The installed adapter and setup path have 22 relevant
unit/regression checks passing; those checks do not prove native compatibility.
Use the documented command in a network-enabled ordinary terminal. On a later
retry, `--skip-install --resume-report <previous comparison.json>` reuses exact
compatible successful Aider rows after rescoring and retries failed rows.

Native Continue and Zoekt comparisons remain pending; this document does not
claim that Aider, Sourcegraph, Continue, Cursor or Copilot has been outperformed.
