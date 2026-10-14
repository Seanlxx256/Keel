# First public-data CORE reference run

This is a single-repository BM25 reference measurement, not an official CORE-Bench score, full-cascade result, or representative benchmark estimate.

## Dataset and execution

- Dataset: `zhangfw123/CORE-Bench`.
- Revision: `23da5d97a8a4495d4bd6d5616aa86d5a12a60699`.
- Export: `data/LEVEL-2/SWE-bench_Verified/pallets__flask`.
- Selection: smallest complete corpus in the pinned Verified Level-2 directory listing; selected before observing retrieval scores.
- Corpus: 1,000 documents; one available, judged query; one positive judgment.
- Query ID: `pallets__flask-5014`.
- Policy: `compass_bm25_reference`, with canonical document IDs and the supplied temporal candidate filter.
- Query limit: 20 requested, one actually evaluated. The first-query subset mechanism did not discard any available query here.
- Operator run: `20261014-185540-ffb5a3a8`, Python 3.11.0 on Windows.

| Metric | Observed value |
| --- | ---: |
| Linear-gain NDCG@10 | 0.0 |
| Positive-label Recall@100 | 0.0 |
| Query retrieval seconds | 0.0104439000133425 |

The timing is one observation and excludes BM25 construction and data loading. It is not a stable latency estimate.

## Input integrity

| Input | SHA-256 |
| --- | --- |
| `corpus.jsonl` | `35afa088130f5f4c4b6c83a0f91b4e63289c647fb75531c46d97ed56a2ca9014` |
| `queries.jsonl` | `0ac296b30c80dee0514941688ba577e9278df0438ec995fe53b19c0d17e4e3da` |
| `qrels.jsonl` | `11e2ae817a89691a142e25d8bb2dc2bd38cd4793ae0c50218bfa75a1b093c5e9` |

Downloaded files and the full result remain local under `.keel/core-public/20261014-185540-ffb5a3a8/`. The public-format loader keeps `authenticity_verified: false` and `public_benchmark_verified: false`; hashes and a pinned download do not establish official evaluator parity.

## Miss diagnosis

A local full-ranking diagnostic using the same BM25 implementation and candidate filter found the positive document `6560b95e-5d41-4f51-bcf2-276115da5e55` at rank **225**, with score approximately **19.7988**. The document exists in the 1,000 eligible candidates. Of those candidates, 819 received positive lexical scores. The top results were documentation snippets; the positive document was a constructor.

This explains the zero cutoff metrics: the target was outside both top 10 and top 100. The checks found no missing label reference or candidate-filter exclusion. They do not independently validate the entire evaluator against the official implementation.

No parameters were changed in response to this query. Further work should predeclare a broader repository/query sample, preserve this baseline, compare retrieval strategies, and keep tuning queries separate from evaluation queries. One miss cannot establish aggregate retrieval quality or motivate a claimed improvement.
