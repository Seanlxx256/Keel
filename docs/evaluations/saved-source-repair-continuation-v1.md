# Saved-source repair continuation: development validation

## Completed Matplotlib attempt

Artifacts: `.keel/swebench/matplotlib-saved-repair-20261021-113104`.
The attempt used the saved failed patch and independently observed test feedback;
Critic reviewed failure, Scout inspected source, Implementer produced two source
insertions, Verifier passed and Auditor reported no findings on new-attempt edits.
Final grading independently reported resolved=true: FAIL_TO_PASS 7/7,
PASS_TO_PASS 89/89; pytest 99 passed, 10 skipped.

Budget: 8 model calls, 37,388 tokens, 12 tool calls, 230.750 Agent seconds.
These totals exclude preceding development attempts and final grading time.
No external MCP calls were made in this attempt. Do not attribute success to
Compass or claim a measured improvement over another model or configuration.

Conditions: reference-verified reconstructed environment using no_pipeline and
remove_unused_vcs_versioning, not original-condition score. This is a new attempt,
not restored conversation state or a replacement score for the interrupted run.
The inherited seed patch did not receive retrospective runtime audit certification.

Trial SHA256: `8ca18307be0c2c57d43f2a293b6b56be42eabce5af5383c49744fec87fe9b618`.

Final grading SHA256: `4ecd0bef78edb2c5832c7336c8b16ad5390a3f7da59c660dc3a4109a67bf59c4`.

## Next development transfer check

Candidate: astropy__astropy-14508, saved failed run
`.keel/swebench/astropy-14508-serena-required-v2/repo`, frozen task and successful
reference under `.keel/swebench/new-task-batch-v1/task-3`.
Local task/reference checks and saved Git base/diff inspection passed. First bind
this existing source to a fresh snapshot grading; if still unresolved with actual
test failures, use the generic continuation runner with unchanged mini model and
fresh output/budget. If grading passes, archive that fact and do not invent failure.
This Astropy task has been used in prior development: it checks cross-task transfer,
not held-out generalization. Do not aggregate the two attempts as a benchmark
success rate. Real transfer outcome is pending; no model or Docker run was started
by this preparation.

## First Astropy transfer outcome

Snapshot `.keel/swebench/astropy-transfer-snapshot-20261021-114134` was unresolved:
FAIL_TO_PASS 1 passed, PASS_TO_PASS 173 passed / 1 failed, no infrastructure error.
Attempt `.keel/swebench/astropy-transfer-repair-20261021-114707` actually edited
source and executed three intermediate verifications, but finished unresolved:
FAIL_TO_PASS 1 passed, PASS_TO_PASS 172 passed / 2 failed. Budget: 28 model calls,
154,424 tokens, 35 tools, 893.235 Agent seconds. The next model-call token reserve
could not fit. This is a failed transfer, not a second successful continuation.
Subsequent development added tested-candidate retention and evidence-bound source
inspection. Their real transfer outcome remains pending; preserve this failure.
