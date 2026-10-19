# Aider and Compass: candidate and ranking complementarity

Four exposed development tasks; retrospective analysis, not held-out evidence.
Artifacts:

- Native Aider: `.keel/tool-checks/aider-retrieval-user-v1/comparison/comparison.json`.
- Pool diagnosis: `.keel/retrieval-validation/aider-diagnostics-v1/diagnosis.json`.
- Fixed interleave: `.keel/retrieval-validation/aider-interleave-v1/comparison.json`.

## Verified mechanism, not a general causal claim

In Pytest 7324, `src/_pytest/mark/expression.py`'s `Expression` class occupies
lines 184-218. Native Aider ranked it first; Compass ranked the identical region
fifth. Compass ranked its `compile` method second. Under the shared 100-line
budget, Aider emitted 32 core-overlap lines and Compass 11. Thus the principal
observed gain is ordering/context allocation, not a region entirely absent from
Compass. Aider's saved pool also includes more relevant regions (79 full overlap
lines versus 55), but candidate caps differ (100 versus 60). These figures do not
isolate a graph-ranking causal effect or prove that extra candidates caused the
emitted-context improvement.

All four saved Aider pools contain some evaluation core overlap, despite three
emitted contexts having zero overlap. This is an ordering/packing observation;
an oracle can reveal potential but cannot be used as a runtime selector. Core
labels describe trajectory reads, not necessarily minimal patch locations.

## One fixed executable mixing rule

Alternate Compass and Aider native candidate ranks, Compass first, deduplicate
exact path/start/end triples, keep at most 100 candidates, pack 100 lines with
32 lines per region. No labels, per-task exceptions, weight search, model calls
or new retrieval enter this rule. Unequal overlapping regions are not merged.
The rule was declared after observing development results; it is not preregistered
held-out evidence. No alternative interleave parameters were tried in this replay.

| Task | Compass recall | Aider recall | Interleave recall |
|---|---:|---:|---:|
| Requests 2317 | 0.632% | 0.000% | 0.632% |
| Pytest 7324 | 4.933% | 14.350% | 14.350% |
| Astropy 8707 | 1.634% | 0.000% | 1.432% |
| Django 14725 | 3.296% | 0.000% | 2.163% |
| Mean | 2.624% | 3.587% | 4.644% |

Mean precision: Compass 38.25%, Aider 8.00%, interleave 35.75%.
Mean file hit rate: Compass and interleave 43.33%, Aider 12.50%.
Interleave has one win, one tie and two losses against Compass. It preserves
some stronger Compass context but still displaces useful lines on two tasks.
Exact-span candidate overlap counts are 7, 4, 4 and 0 respectively; different
chunk boundaries mean this is not a measure of total semantic overlap.

## Decision and next evidence needed

Do not promote the mixer or route by known task scores. Keep original Compass
as the default. Treat Aider's native graph ordering as a concrete source of ideas
for structure-aware ranking, and evaluate candidate acquisition separately from
ordering on disjoint tasks. Any learned/routed policy requires a development/
validation split and cannot infer its own best arm from these labels. Full-agent
comparisons remain separate from this component-level experiment.

Reproduce without installation or inference, using new output directories:

```powershell
python examples/analyze_retrieval_candidates.py --source .keel/retrieval-validation/run-v12/source-result.json --external .keel/tool-checks/aider-retrieval-user-v1/comparison/comparison.json --output .keel/retrieval-validation/aider-diagnostics-v2
python examples/replay_candidate_interleave.py --source .keel/retrieval-validation/run-v12/source-result.json --external .keel/tool-checks/aider-retrieval-user-v1/comparison/comparison.json --output .keel/retrieval-validation/aider-interleave-v2
```

The replay verifies query, dataset, source-report and index identities, reproduces
both original metrics, records input/implementation hashes and rejects duplicate
task rows or changed historical inputs. Two interleave regression checks plus
eight existing Aider/external-comparison checks passed in this increment.
