# Fixed-ranking context budget ablation

On 2026-10-14, saved candidates from the final-policy three-repository run
`bdb1b28a48574f5fa371d7f53271854e` were repacked under total line budgets
100/300/500 and symbol caps 32/64. All three independent instances and both
rankings were retained. This is 144 packing/scoring records derived from 24 source
retrieval runs, not 144 independent tasks or new retrieval executions.

The experiment fixes candidate order and final model-selected symbols. It changes
only packing, so it isolates the direct budget effect without model variance.
It makes zero new model or embedding calls. Full replay artifacts are at
`.keel/context-budget-replay-final/`; [the compact archive](context-budget-ablation.json)
retains input/implementation hashes, exclusions, and all configuration means.

## Code-aware T1

| Total lines | Symbol cap | Mean line recall | Mean line precision | Mean emitted lines |
| --- | --- | --- | --- | --- |
| 100 | 32 | 3.16% | 42.67% | 100 |
| 300 | 32 | 6.22% | 26.44% | 300 |
| 500 | 32 | 9.28% | 21.80% | 500 |
| 100 | 64 | 3.93% | 52.00% | 100 |
| 300 | 64 | 7.04% | 29.33% | 300 |
| 500 | 64 | 12.55% | 31.00% | 500 |

Increasing total output budget improves recall in this fixed-ranking sample but
reduces precision at a fixed symbol cap. Changing the cap has a different effect:
64-line prefixes improve both mean recall and precision here. This is a development
observation, not evidence to promote a universal cap or budget default.

## Code-aware T2

At symbol cap 32, mean recall remains 0.77% for all three total budgets. Only
26.3 lines are emitted on average. At cap 64, recall is 1.54% at every total
budget, with 47.7 emitted lines. Larger total budgets do not expand the fixed
model selections; they mostly remain unused. Enlarging individual symbol windows
does add lines, which may extend beyond what the original reader inspected.
These are replayed contexts, not a claim of new model-verified evidence.

This separates two bottlenecks: T1 can recover more evidence by emitting more
candidates, while T2 also needs better evidence selection. Merely increasing
time, call or token limits would not alter these already-completed selections.

## Line-budget-normalized recall, audited from saved records

For each task let N be deduplicated gold/core lines, B the total line budget,
H the correctly retrieved unique lines, and P emitted unique lines. The relaxed
line-count recall bound is U = min(B, N) / N. Normalized recall is
(H/N) / U = H / min(B, N). Average this ratio within tasks before averaging tasks;
do not divide mean recall by mean ceiling or substitute an average gold size.

Code-aware T1, B=100 and symbol cap 32:

| Task | Gold lines N | Line-count bound U | Actual recall | Fraction of bound |
| --- | ---: | ---: | ---: | ---: |
| Flask 5014 | 626 | 15.97% | 3.19% | 20.00% |
| Requests 1724 | 1,385 | 7.22% | 4.62% | 64.00% |
| Seaborn 3069 | 2,627 | 3.81% | 1.67% | 44.00% |

Equal-task mean fraction: **42.67%** (RRF T1: **14.33%**). These are three
development tasks, not a general benchmark or confidence estimate.

At symbol cap 32, fixed-ranking replay gives:

| Total budget | Mean recall | Mean fraction of line-count bound | Mean correct lines |
| --- | ---: | ---: | ---: |
| 100 | 3.16% | 42.67% | 42.67 |
| 300 | 6.22% | 26.44% | 79.33 |
| 500 | 9.28% | 21.80% | 109.00 |

The additional 200 lines from 100 to 300 yield 36.67 more correct lines on
average (18.33% marginal yield); the next 200 yield 29.67 (14.83%). This supports
diminishing line-budget yield in this saved sample. It does not establish a
live T1-to-T2 escalation threshold, token cost or downstream repair improvement.

Here all N exceed B and T1 uses the full output budget (P=B), so normalized
recall H/B is **exactly line precision H/P**. More generally with N>=B it equals
precision times budget utilization P/B. It is a useful alternate interpretation,
not a second independent performance improvement. Gold regions are broad and
do not prove exact edit localization. The bound ignores candidate availability,
symbol prefix caps and packing restrictions; call it a relaxed line-count bound,
not an achievable oracle or a demonstrated maximum for this retriever.

## Scope

Source configurations must have completed all repetitions; successful repetitions
from an ineligible configuration are not included. Repetition means are computed
within each task before equal-task means. A line-count-only ceiling is retained
per record as `min(line_budget, core_lines) / core_lines`, with utilization and
ceiling-normalized recall. The ceiling does not guarantee that relevant lines are
available through the candidate list or prefix packing.

This remains three development instances with broad gold regions and no official
evaluator parity. Replay does not establish live model behavior, latency changes,
downstream coding success, or generalization. A practical next test is 300 total
lines with a 64-line cap on additional independent tasks; keep the existing
100/32 baseline for comparison and avoid changing defaults based on this sample.
