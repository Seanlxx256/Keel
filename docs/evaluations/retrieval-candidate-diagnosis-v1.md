# Saved retrieval candidate diagnosis

Artifact: `.keel/retrieval-diagnostics/v1/diagnosis.json`. No new model,
retrieval, or indexing calls. No runtime defaults changed. This analysis reads
cached exposed development trajectories and verifies source/query/index receipts.

## Observations

Entries are unique reference-core lines in all saved candidate ranges, after a
32-line per-candidate prefix cap, and in final ranked 100-line output. These
are counts, not percentages or minimal repair locations.

| Engine/task | Candidates | First core overlap rank | Full pool | Capped pool | Emitted |
|---|---:|---:|---:|---:|---:|
| Compass code-aware / Flask | 60 | 2 | 591 | 157 | 20 |
| Compass code-aware / Requests | 56 | 1 | 1054 | 262 | 64 |
| Compass code-aware / Seaborn | 56 | 2 | 1883 | 279 | 44 |
| Serena / Flask | 5 | 1 | 588 | 64 | 64 |
| Serena / Requests | 59 | 17 | 207 | 109 | 0 |
| Serena / Seaborn | 31 | 1 | 181 | 54 | 54 |
| CocoIndex / Flask | 100 | 4 | 222 | 222 | 29 |
| CocoIndex / Requests | 100 | 5 | 597 | 567 | 6 |
| CocoIndex / Seaborn | 100 | 8 | 277 | 271 | 0 |

All three engines have saved core-overlapping candidates on every task.
CocoIndex Seaborn's first overlap is rank 8 (`seaborn/_core/plot.py:619-648`);
rank 10 overlaps `seaborn/_core/scales.py:160-174`. The output budget is already
consumed by earlier chunks. Serena Requests likewise first overlaps at rank 17
and emits no core lines. A zero packed recall is not proof of zero candidate
recall.

The Compass reference-core pool is large, but a universal 32-line symbol prefix
discards much of it before total-budget selection. Reordering alone cannot
recover lines already removed from candidate prefixes. The identical full/capped
pool coverage between saved Compass RRF and code-aware ranking, alongside
different emitted hits, isolates an ordering effect on this candidate pool.

## Interpretation and next experiment

The next experiment should evaluate a fixed reranker on saved full candidates
and use the same packing policy first, separating ranking from packing changes.
Then compare a separate query-aware snippet policy with the prefix baseline.
Freeze choices before validation on new tasks. Avoid adding another embedding
model before establishing whether it addresses missing candidates or ordering.

This is evidence of a selection bottleneck against read-core labels, not proof
that all required repair context is present. Core labels often include whole
files. Candidate sets and symbol/chunk granularity differ; the experiment is not
a matched query-cost benchmark. Budget-loss counts include unavoidable capacity
limits and should not all be called ranking errors.

The report's optimistic line oracle selects reference lines directly. It is an
evaluation upper bound, not executable retrieval or promised reranker quality.
No gold-derived selection has been fed back to Keel or the retrievers.

## Reproduce

```powershell
python examples/analyze_retrieval_candidates.py --source .keel/swe-public/bdb1b28a48574f5fa371d7f53271854e/result.json --external .keel/retrieval-alternatives/v4/comparison.json .keel/tool-checks/cocoindex-evaluation-v3/comparison/comparison.json --output .keel/retrieval-diagnostics/v2
```

Input hashes and implementation hashes are saved; scoring rejects invalid file
ranges and mismatched query/index/dataset identities. This command is offline.
