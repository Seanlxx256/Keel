# Matplotlib reference environment recovery

Task: matplotlib__matplotlib-25775. This is a reconstructed-environment
reference preflight, not an Agent repair or original-condition benchmark score.

The original optional-tool comparison retained its reference build failures.
APT download failures were diagnosed separately; the live network ReAct v3
completed the diagnostic workload under an isolated no-pipeline policy.
Reference grading then ran but failed: 35 failed, 66 passed, 8 skipped.
Inspection reproduced a duplicated SCM version-scheme entry point: the
vcs-versioning provider raised DeprecationWarning while setuptools-scm's own
provider passed. The guarded recovery requires fresh evidence and no active
reverse dependency before removing only the conflicting optional provider.

Verified run: `.keel/swebench/matplotlib-scm-recovery-v1/recovery.json`.
It performed inspection, applied the registered container-only policy and
automatically continued into official harness grading:

- status: reference_verified_reconstructed
- official_resolved: true; patch successfully applied; no reported infra failure
- FAIL_TO_PASS: 7 successful, 0 failed
- PASS_TO_PASS: 89 successful, 0 failed
- pytest summary: 99 passed, 10 skipped
- harness instance execution: approximately 21 minutes including image work
- report SHA256: d152a9f62dbfa970403cb5d38ff710f64961bb90ca68eee961b4b02dda740545

Transport and plugin policies are recorded separately and use a distinct image
tag. Source, test patch and acceptance commands remain unchanged. The live
verification guard also passed after evaluation-stage installation. No host
package was uninstalled. This demonstrates a known-family recovery followed by
independent reference validation; it does not establish arbitrary self-repair,
prove pipelining was the sole network cause, or repair the task with an Agent.

The old paired-comparison result stays unchanged. To run the third task's two
Agent arms, propagate the same declared policies to every verification and final
grade, then freeze a separate continuation protocol with current implementation
hashes. Do not reuse the original frozen plan after implementation changes or
combine its first-attempt outcomes silently with reconstructed retries.
