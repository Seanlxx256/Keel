# Fixed equal-weight rank fusion

Artifact: `.keel/retrieval-reranking/fusion-v1/fusion.json`.

The protocol was declared before this replay: equal-weight reciprocal-rank
fusion of baseline and MiniLM reranker ranks, constant 60, baseline order for
ties. No parameter search, candidate merging, changed snippet ranges or new
inference. This policy was chosen after viewing previous development results;
it is not preregistered held-out evaluation.

The replay verifies all original reranking input receipts, query/code inputs,
candidate identity, scores and permutations. Both original and reranked metrics
must reproduce before fusion is scored. The same 100-line budget and 32-line
candidate-prefix cap apply. Original inference cost (567 scored pairs) is retained
as provenance; the replay itself makes zero model calls.

## Results

Macro line recall (%):

| Engine | Original | Reranked | Fused |
|---|---:|---:|---:|
| Compass code-aware | 3.16 | 4.28 | 4.01 |
| Serena symbols | 4.09 | 4.20 | 4.09 |
| CocoIndex semantic | 1.69 | 2.30 | 2.61 |

Original → fused line recall by task (%):

| Engine | Flask | Requests | Seaborn |
|---|---:|---:|---:|
| Compass | 3.19 → 9.74 | **4.62 → 0.43** | 1.67 → 1.87 |
| Serena | 10.22 → 10.22 | 0.00 → 0.00 | 2.06 → 2.06 |
| CocoIndex | 4.63 → 5.59 | 0.43 → 2.24 | 0.00 → 0.00 |

Mean line precision original → fused: Compass 42.67% → 38.67%, Serena
48.48% → 48.48%, CocoIndex 11.67% → 22.00%. Mean core-file hit rate is unchanged
from original for all three engines. These metrics are read-core coverage,
not task repair success or evidence that all required fix context is present.

Fusion improves two CocoIndex development cases and ties one, but also removes
the reranker-only gain on Seaborn. Compass's serious Requests regression remains.
Serena has unchanged packed metrics; that does not imply identical permutations.
RRF is not a fallback guarantee, and improved macro averages do not make it safe
to replace baseline ordering.

## Decision

No runtime default is promoted. Do not tune weights/constants to these three
labels. Keep baseline, reranker-only and this fixed fusion policy as explicit
experimental arms. Before adopting one, freeze the arms and evaluate new tasks,
including per-task regressions, precision, file coverage and scoring cost.
A code-specialized reranker would be another model experiment, not evidence
that this fixed fusion solved the existing regression.

## Reproduce offline

```powershell
python examples/replay_retrieval_fusion.py --source .keel/swe-public/bdb1b28a48574f5fa371d7f53271854e/result.json --external .keel/retrieval-alternatives/v4/comparison.json .keel/tool-checks/cocoindex-evaluation-v3/comparison/comparison.json --evaluation .keel/retrieval-reranking/minilm-v2/evaluation.json --output .keel/retrieval-reranking/fusion-v2
```

Validation: nine real saved task/engine pairs replayed with identity and metric
checks. Thirteen related tests passed, including permutation integrity, tie
handling and rejection of altered source receipts. No benchmark or online agent
performance claim is made.
