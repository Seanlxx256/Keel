# Flask candidate and context diagnostics

The 2026-10-14 follow-up used the same snapshot, index, issue, seed, 100-line
budget, model names, and per-run limits as
[the protocol validation](swe-flask-protocol-validation.md).
Artifacts: `.keel/swe-context-packing-validation/`; three repetitions per mode.

## Findings

The hybrid candidate list contained relevant code, including
`test_dotted_name_not_allowed` at rank 12, `Blueprint.register` at rank 47,
`Blueprint` at rank 49 and `Blueprint.__init__` at rank 57. The first candidate,
`Flask.url_for`, spans 124 lines and previously exhausted the entire 100-line
budget. T2 selected this first candidate explicitly, excluding the other candidates.

Full-range T1 candidate diagnostics cover 4,797 unique lines with core-file hit
rate 1.0 and line recall approximately 0.9441. These are post-retrieval diagnostics
over unrestricted symbol ranges, not achievable quality within a 100-line budget.
They indicate available evidence, including a large class range, rather than
demonstrating precise localization. Gold labels never enter retrieval or packing.

## Change and measured result

Context packing now emits at most 32 prefix lines per ranked symbol and skips
already emitted lines. It preserves ranking and never exceeds the line budget.
The 32-line cap is a fixed heuristic, not calibrated on held-out data. Reports
retain the packing policy and returned candidate ranges, keeping these results
distinct from earlier unlimited-prefix runs. Historical results are unchanged.

| Mode | Completed | Emitted lines | Core-file hit rate | Line recall |
| --- | --- | --- | --- | --- |
| T0 | 3/3 | 0 | 0 | 0 |
| T1 | 3/3 | 100 | 0.5 | 0 |
| T2 | 3/3 | 32 | 0 | 0 |
| Adaptive | 3/3 | 32 | 0 | 0 |

T1 now includes five regions across four files instead of exhausting the budget
on one function. Its core-file hit rate rose from 0 to 0.5; line recall did not
improve. T2 and adaptive still choose the wrong function. No extra symbols are
inserted after the model's final selection to conceal this failure.

Additional observability changes retain the hybrid ranking before model selection
in `retrieval_candidates` sweep events. Exploration previews now expose metadata
for every newly visible ID, retaining code excerpts only for the first five;
previously later IDs could become selectable without appearing in the observation.
The live run above did not exercise query/graph expansion, so that preview fix is
covered by regression tests rather than claimed as a measured quality improvement.

Next work should compare query/code-aware ranking and evidence selection across
multiple development instances, then validate on held-out repositories. One
instance and repeated shared caches cannot establish benchmark-wide improvement
or reliable timing. Official evaluator parity remains unverified.
