# Final-policy three-repository development validation

The 2026-10-14 run at `.keel/swe-public/bdb1b28a48574f5fa371d7f53271854e/`
completed all 24 retrieval runs in approximately 357 seconds. Each of the three
development instances was evaluated under two ranking policies and four modes,
with one repetition. All three repository snapshots and compatible semantic
indexes were verified and reused. No modes were excluded from paired summaries.

Instances: `pallets__flask-5014`, `psf__requests-1724`, and
`mwaskom__seaborn-3069`. Settings: seed 42, 100-line context budget, read evidence
policy, 8K chat context, 32-line symbol cap, and local `keel-chat` / `keel-embed`.
Per-run limits stayed at 300 seconds, 30,000 tokens, four model calls, and
100 tool calls. Data revisions and input hashes remain in the frozen plan.

## Equal-instance means

| Policy/mode | Line recall | Line precision | File hit rate | Mean model calls |
| --- | --- | --- | --- | --- |
| RRF T1 | 0.00546 | 0.14333 | 0.47222 | 0 |
| Code-aware T1 | 0.03164 | 0.42667 | 0.72222 | 0 |
| RRF T2 | 0.00063 | 0.05556 | 0.11111 | 2 |
| Code-aware T2 | 0.00770 | 0.33333 | 0.25000 | 2 |
| Code-aware adaptive | 0.00770 | 0.33333 | 0.25000 | 2.66667 |

T0 completed with zero matches for these natural-language issue queries, which
are outside its exact-symbol/path use case. Code-aware T1 increased average
recall by about 2.62 percentage points over RRF T1 in this development sample.

## Escalation findings

Within code-aware ranking, T2 reduced recall on all three instances, with mean
recall delta -0.02393 and precision delta -0.09333 relative to the same-instance
T1 baseline. Mean model calls increased by two. RRF T2 tied T1 recall on two
instances and reduced it on one. No tested escalation increased core-line recall.
Actual retrieval seconds also increased, but timing is descriptive because model
loads and caches are uncontrolled.

The read policy prevents selecting unread symbols and produced real read/selection
trajectories. It does not ensure that selected evidence is sufficient. Narrow
model selections discard useful T1 candidates; execution completion alone is not
evidence of quality improvement. These findings do not justify promoting T2 over
T1 or declaring the upgrade gate calibrated.

Next work should isolate candidate exposure, source reading, and final evidence
selection in controlled ablations. Defaults should not be tuned against these
three labels. Broader independent tasks and held-out repositories are required
before claiming generalization or selecting an online upgrade threshold.

## Evidence and reporting

[The archived JSON](compass-final-policy-three-repo.json) preserves the source
result hash, pinned sources, settings, per-instance results and derived comparisons.
Raw per-policy sweeps retain model replies, observations, preflight estimates,
read IDs and costs. A post-run analysis at the artifact directory's `analysis/`
contains `comparison.json` and `comparison.md`; the original results are unchanged.

The reporting implementation now includes paired quality/cost means, same-task
T2/adaptive-minus-T1 deltas, per-metric improvement/tie/regression counts, and
explicit exclusions. `python -m compass.comparison` can regenerate these reports
from a saved result without retrieval or model calls and refuses output overwrite.

This is one repetition on three development tasks, not a full benchmark or a
held-out evaluation. Gold regions include broad file ranges; line overlap does
not demonstrate precise edit localization. Historical runs with other prompt,
ranking or residency policies remain separate. Official evaluator parity and
leaderboard results are unverified.
