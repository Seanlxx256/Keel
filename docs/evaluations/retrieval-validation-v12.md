# Retrieval validation v12: paired development results

Source: `.keel/retrieval-validation/run-v12/validation.json` and
`fusion/fusion.json`. Reproducible offline analysis:

```powershell
python examples/analyze_retrieval_validation.py --run .keel/retrieval-validation/run-v12 --output .keel/retrieval-validation/analysis-v12
```

The output directory must be new. The analyzer checks historical input hashes,
compares engines on their common task IDs and writes JSON plus Markdown without
new indexing, inference or ranking changes. Existing relevance labels are used
only for retrospective analysis, never for runtime routing.

## Operational outcome

Four tasks have results for Compass, Serena and CocoIndex. Django's native index
checkpoint continuation and subsequent search succeeded. Xarray remains an
explicit input-validation failure; five-task completion is not claimed.
The corpus policy is valid-python, not strict full-corpus completeness.

## Compass recall by task

| Task | Original | Reranked | Fused |
|---|---:|---:|---:|
| Requests 2317 | 0.632% | 0.000% | 0.632% |
| Pytest 7324 | 4.933% | 0.000% | 14.350% |
| Astropy 8707 | 1.634% | 0.828% | 0.828% |
| Django 14725 | 3.296% | 0.103% | 1.802% |

Compass fusion increases mean recall from 2.624% to 4.403%, but has one win,
one tie and two losses. Without Pytest, its mean paired change is -0.766
percentage points. The apparent average gain is concentrated in one task.
Precision declines from 38.25% to 27.25%. Mean file hit rate rises from 43.33%
to 48.33%. These are descriptive development results, not significance or
generalization claims.

CocoIndex fusion has two wins, one tie and one loss but lowers mean recall
from 0.984% to 0.637%. Serena fusion has no wins, three ties and one loss.
The generic reranker alone also lowers mean recall for all three engines.
Neither fusion nor reranking is promoted to the default.

## Next experiment protocol

1. Retain original Compass as the default and retain these task IDs as exposed
   development tasks. Never select an arm from its known task-level score.
2. Before execution, freeze new disjoint task IDs, source commits, models,
   implementation identities and budgets. Keep the current reranker and fixed
   equal-weight RRF constant 60; do not tune them from this report.
3. Run original, reranked and fused arms on identical candidate pools and the
   existing 100-line / 32-line-per-symbol packing policy. Preserve explicit
   input and infrastructure failures and report common-task coverage.
4. Report task-level recall, precision, file hits and win/tie/loss counts beside
   means. Do not promote an arm solely from mean recall when precision or most
   tasks regress. More tasks are required before choosing a deployment policy.
5. Separately evaluate end-to-end repair under equal model/tool/time budgets;
   retrieval metrics cannot establish an improvement in official repair scores.

No new task batch has been executed by this analysis. Model prior exposure is
unknown; even disjoint task IDs alone do not establish a held-out benchmark.
