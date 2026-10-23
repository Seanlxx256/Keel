# GPT-5.4 continuation accepted, 2026-10-23

Task: astropy__astropy-14508. This is a developer-assisted, exposed saved-source
continuation with historical controls, not an independent first-attempt score.
Benchmark-ready remains false. Prior unsuccessful attempts and costs remain.

Evidence root: `.keel/swebench/astropy-full-repair-v2`.

- `trial.json`: runtime passed, official_resolved true, no failure/grading error.
- `final-grade/grading.json`: graded, patch applied, no infrastructure failure.
- Official per-instance report: FAIL_TO_PASS1success/0failure,
  PASS_TO_PASS174success/0failure, including test_invalid_float_cards2.
- `run/result.json`: audit changed only astropy/io/fits/card.py, no unexpected
  changes/findings; metadata_checked false. Audit scope does not retrospectively
  certify inherited edits.
- `run/changes.patch`: new-attempt patch SHA256
  48b2537b6e52a63e86390ca808931862f25dc8779a5d9b6e31ea62273e146723.

Model-designed probe exercised candidate formatting, card serialization and the
actual initial HDU write. Model generated a helper normalizing representation
case/exponent formatting for both short-string and fallback paths, retaining
short decimal rendering. Host did not supply a source repair branch or edit the
candidate to insert this fix. Independent verification then passed; final grading
also passed. One new verification round; no post-edit repair round was needed.

Cost:8modelcalls,93,158reported tokens,19tools;325.688agent seconds (includes
verification),521.375total trial seconds.2/6recovery actions used (saved
failure assessment and one source reselection). Keep nested limits distinct.

V1 versus v2:11->8calls,125,803->93,158tokens, unresolved->accepted. Not a clean
causal/cost ablation: stochastic model outputs and evidence choices also differ;
v1 failed early while v2 ran verification. Request compaction removes the known
admission obstacle, but no broad percentage improvement or generalization claim.

Next: preserve this successful trajectory; inspect repeated source reads, request
duplication and verification overhead before proposing cost reductions. Test any
change against this frozen starting state, then independent held-out cases. Do
not immediately rerun the accepted task or treat this case as unexposed evidence.
