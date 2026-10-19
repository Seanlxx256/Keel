# Structural validation v1: partial results accepted

Frozen plan: `.keel/structural-validation/plan-v2/plan.json`, SHA-256
`2fd18df4bc9b3581da4c01aec5713d5975caecfc9c8dbec901e963da90a9481f`.
Run: `.keel/structural-validation/run-v1/run.json`.
Audit: `.keel/structural-validation/run-v1/acceptance.json`.

Two of five planned tasks have complete three-arm results. The audit verified
the frozen implementation/task identities, all five task receipt hashes and
completed-task artifact hashes. It checked index freshness, replayed all metrics
for both completed tasks and verified unchanged candidate IDs in the structural
arm. No new model calls, indexing or parameter tuning occurred during acceptance.

| Arm (same two tasks) | Mean line recall | Mean line precision | Mean file hit rate |
|---|---:|---:|---:|
| Original Compass | 6.604% | 73.50% | 75.00% |
| Same-pool structural ranking | 6.791% | 76.50% | 75.00% |
| Native Aider ranking component | 1.583% | 13.00% | 25.00% |

Requests 6028: original precision 79%, structural 85%; recall 4.925% to 5.299%.
Pytest 7571: original and structural precision 68%, recall 8.283% (tie).
Structural outcome: one improvement, one tie, no regression among the two
completed tasks. This is insufficient evidence for general superiority or
default promotion. Aider is the disclosed native ranked-tag component, not its
full Agent or rendered repo map. These task IDs are disjoint from earlier local
exposure but are public and not verified training-unseen.

## Retained incomplete tasks

- Xarray 3993: baseline status `unindexed_reference_files`; reference ranges
  include `doc/computation.rst` and `doc/whats-new.rst`. The current corpus is
  Python-only. Do not silently drop reference ranges or count this as zero recall.
- Astropy 12907: index deadline at about 896 seconds, progress 7,712 / 17,854
  vectors. Checkpoints retained; no three-arm quality score.
- Django 16116: shared recovery deadline at about 899 seconds, progress
  7,808 / 37,363 vectors. Checkpoints retained; no three-arm quality score.

Next, continue the two bounded index builds using existing checkpoints and retain
the Xarray coverage exclusion unless a separately declared corpus protocol
supports its documentation. Do not substitute tasks or change structural weights
in response to these scores. Keep original Compass as the default until broader
paired evidence is available. Partial completion may introduce selection bias;
the two-task means cannot be presented as five-task results or official repair
scores. No production or statistically significant improvement is claimed.
