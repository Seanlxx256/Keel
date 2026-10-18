# Infrastructure recovery follow-up

The five-task v2 batch remains unchanged. Subsequent infrastructure retries must use
new output directories and are not retroactive first-attempt scores.

Implemented generic fixes:

- Harness subprocess forces PYTHONUTF8=1 in addition to stdio encoding. This covers
  ordinary open/write calls inside the official harness, without modifying its package.
  A real child-process test writes U+263A using the default file encoding.
- Snapshot publication retries PermissionError at most four times, with increasing
  waits totalling three seconds. It refuses existing destinations, preserves staging on
  persistent failure, checks the published snapshot, and saves a publication receipt.
  Tests cover transient locks, permanent locks and destination collision. The actual
  Matplotlib lock source is not identified; retries cannot fix permanent ACL problems.

Follow-up implementation and remaining verification:

- Bounded packaging compatibility recovery is now implemented separately in
  `examples/recover_swebench_environment.py`; see `docs/harness-environment-recovery.md`.
  Its real Pylint outcome is still unverified. The Pylint image failed because editable
  installation lacks a build_editable hook, but this log alone does not establish which
  exact pin should change. A compatibility experiment must record original/modified
  build recipes, isolate image/cache identity, retain errors, and pass reference preflight.
  Do not silently monkey-patch the official installer or relabel modified conditions.
- Mandatory execution of Critic next_check. Diagnosis handoff and source evidence
  exist, but a declared diagnostic check is not yet a machine-verified experiment.
  A future implementation should support bounded read/probe actions with evidence IDs,
  prohibit arbitrary host commands, and associate results with the hypothesis before edits.
- No real Docker or model retry was performed for this follow-up. Deterministic tests
  establish the local fixes, not successful reruns of the failed benchmark tasks.
