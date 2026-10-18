# Frozen-candidate reranking experiment

The first ranking-only experiment uses installed Sentence Transformers
`CrossEncoder` with `cross-encoder/ms-marco-MiniLM-L6-v2`, a general MS MARCO
model, **not a code-specialized reranker**. It is a small runnable baseline,
not a recommendation that it is the best model for code.

Primary interfaces:
[CrossEncoder API](https://www.sbert.net/docs/package_reference/cross_encoder/model.html),
[model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2).

## Fixed protocol

- Saved Compass code-aware, Serena and CocoIndex candidates are evaluated
  separately on the three exposed development tasks; no candidate fusion.
- Exact candidate ranges, source text and total candidate membership stay fixed.
- The worker receives only issue text and path/code strings. Labels and source
  datasets are never sent to it. It returns scores and a complete permutation.
- Pair input is the full issue and `path + newline + full candidate source`.
  Upstream tokenizer truncation is limited to 512 tokens per pair. It may omit
  important code/query text; this baseline does not claim otherwise.
- CPU execution, four torch threads, seed zero and batch size eight are fixed.
  Scores must be finite; equal scores preserve original order.
- The original 100 unique-line budget and 32-line candidate-prefix cap remain.
  No gold-aware snippet selection or packing change is introduced.
- Source/query/index identity, candidate ranges, input hashes and source
  fingerprints are validated. Failed inference has no quality score.
- Both baseline and reranked results are rescored using the same evaluator.
  Package versions, requested/resolved model revision, per-job scores, order and
  timings are saved. A missing resolved revision means weights are not pinned.

## Execute

Reuse the CocoIndex venv with sentence-transformers/torch already installed:

```powershell
python examples/evaluate_retrieval_reranker.py --source .keel/swe-public/bdb1b28a48574f5fa371d7f53271854e/result.json --external .keel/retrieval-alternatives/v4/comparison.json .keel/tool-checks/cocoindex-evaluation-v3/comparison/comparison.json --output .keel/retrieval-reranking/minilm-v2
```

No generation-model API key is needed. The first run needs access to Hugging
Face for model weights. A fresh output directory preserves prior attempts.
`--revision` can pin a weight revision; `--local-files-only` disables fetching.
The script logs the active stage every ten seconds and defaults to a 1800-second
worker limit. Model cache lives under the output parent directory. New weights
are downloaded by the upstream loader; remote model code execution is disabled.

`evaluation.json` contains paired before/after quality per engine. Worker
inference count is recorded separately from generation-model calls. Loading and
download time are not warm scoring latency. These three tasks cannot establish
statistical significance, held-out improvement or Keel repair success.

## Current execution evidence

The initial local run is preserved at `.keel/retrieval-reranking/minilm-v1`.
The execution environment refused Hugging Face connections during model loading.
No neural-quality result is available from that attempt. Interface/permutation
tests use an explicitly stubbed model and validate orchestration only; they do
not substitute for actual inference.

## Completed run: minilm-v2

The user-terminal run `.keel/retrieval-reranking/minilm-v2/evaluation.json`
completed nine task/engine pairs (567 query/code pairs). Installed versions:
sentence-transformers 6.1.0, torch 2.14.1, transformers 5.20.1. The resolved
weight revision was not captured (null); these are not independently pinned
model weights. Total worker time was 61.14s, including 33.36s model loading;
per-engine/task scoring took 0.28–5.39s. Download/cache state affects loading.

Line recall before → after (%):

| Engine | Flask | Requests | Seaborn | Macro mean |
|---|---:|---:|---:|---:|
| Compass code-aware | 3.19 → 10.54 | 4.62 → 0.00 | 1.67 → 2.28 | 3.16 → 4.28 |
| Serena symbols | 10.22 → 10.22 | 0.00 → 1.16 | 2.06 → 1.22 | 4.09 → 4.20 |
| CocoIndex semantic | 4.63 → 3.04 | 0.43 → 2.24 | 0.00 → 1.64 | 1.69 → 2.30 |

Mean line precision changes are Compass 42.67% → 42.00%, Serena 48.48% →
46.48%, CocoIndex 11.67% → 31.00%. Core-file hit rate falls for Compass and
Serena, and increases for CocoIndex. Macro recall averages task-level ratios
with different denominators, so an increase can coexist with reduced mean
precision and fewer covered files. It is not uniform improvement.

The severe Compass Requests regression rules out adopting this reranker as an
unconditional replacement based on these results. The experiment demonstrates
that selection changes matter, while this general-text reranker is inconsistent
on code. No default runtime ranking has been changed. A next controlled
experiment may preserve baseline-ranked evidence via a fixed rank-fusion policy,
or test a code-trained reranker, but must keep these tasks designated as
development and evaluate a frozen choice on new tasks before promotion.
