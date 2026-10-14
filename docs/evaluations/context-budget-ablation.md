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
