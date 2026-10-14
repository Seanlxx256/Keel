# Verified Level-2 public-data BM25 baseline

This run completed all 12 repositories in the pinned Verified Level-2 export. It is a Compass BM25 reference measurement on a fixed query sample, not full CORE-Bench coverage, an official evaluator result, or a full T0/T1/T2 cascade comparison.

## Protocol

- Dataset revision: `23da5d97a8a4495d4bd6d5616aa86d5a12a60699`.
- Directory: `data/LEVEL-2/SWE-bench_Verified`.
- Run: `20261014-192307-f6890f36`, Python 3.11.0 on Windows.
- Full corpora: 398,397 documents across 12 repositories; no document sampling.
- Judged queries available: 432; evaluated: 173, capped at 20 per repository with seed 42.
- Query selection hashes the seed, repository name and query ID; relevance labels do not determine sampling.
- Three repetitions rebuild BM25 independently. Quality counts each selected query once. Latency includes scorer construction and progress logging, with uncontrolled OS caches.
- Temporal candidate filters, canonical IDs, linear-gain NDCG@10 and positive-label Recall@100 are preserved.
- All inputs were pinned with local SHA-256 hashes; originals were not edited. Identical qrel duplicates were merged once for xarray, while conflicting grades remain errors.

## Results

| Aggregation | NDCG@10 | Recall@100 |
| --- | ---: | ---: |
| Query-weighted mean | 10.0514% | 29.0425% |
| Repository mean | 8.1655% | 27.9595% |

| Repository | Documents | Selected / available queries | NDCG@10 | Recall@100 | Mean repeat seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| astropy__astropy | 66,203 | 20 / 22 | 17.7564% | 47.0833% | 24.178 |
| django__django | 85,483 | 20 / 188 | 9.0879% | 28.2500% | 26.807 |
| matplotlib__matplotlib | 42,522 | 20 / 32 | 6.4453% | 20.1667% | 13.976 |
| mwaskom__seaborn | 2,515 | 2 / 2 | 0.0000% | 41.6667% | 0.344 |
| pallets__flask | 1,000 | 1 / 1 | 0.0000% | 0.0000% | 0.146 |
| psf__requests | 2,356 | 8 / 8 | 2.3072% | 47.9167% | 0.422 |
| pydata__xarray | 18,007 | 18 / 18 | 7.7047% | 22.5926% | 5.421 |
| pylint | 19,438 | 9 / 9 | 11.1111% | 17.0370% | 3.173 |
| pytest | 15,455 | 15 / 15 | 11.1050% | 25.6667% | 3.781 |
| scikit | 38,876 | 20 / 26 | 22.0731% | 40.1667% | 12.831 |
| sphinx | 19,076 | 20 / 42 | 1.5329% | 7.8846% | 5.214 |
| sympy__sympy | 87,466 | 20 / 69 | 8.8626% | 37.0833% | 21.296 |

## Verification and artifacts

All 12 repositories passed input-integrity checks and produced three ranking artifacts each. A separate calculation from the saved rankings and qrels reproduced all 519 query-run metric pairs. Rankings were identical across repetitions. The previous 11 successful repositories retained exactly the same input hashes, selected queries, and quality metrics; the new aggregate includes the previously failed xarray repository.

[The portable result snapshot](core-verified-baseline.json) records selected query IDs, input/implementation/manifest hashes, summaries, per-repository metrics, and repeated timings. Full local artifacts remain under `.keel/core-verified-batch/20261014-192307-f6890f36/`, including the input manifest, progress log, repository checkpoints, raw ranking files, and CSV. The downloaded corpus is not committed.

## Limits and next step

`public_benchmark_verified` remains false: official evaluator parity and trusted-origin verification are separate from a successful local run. Corpus versions are pooled as provided; queries use their supplied temporal eligibility filters. These sampled, repository-specific means must not be compared directly to paper-wide aggregate scores. This experiment has no semantic embedding model, reranker, T2 model, routing calibration, or demonstrated improvement.

Preserve this baseline. The next experiment should compare the real cascade on explicit SWE-Explore code snapshots, with fixed context budgets, real embedding/chat models, and repository-separated tuning and evaluation sets.
