# Intake v2: no repair executions and discovery-policy limitations

The saved campaign searched six repositories, charged 73 metadata tool calls, took 419.797 seconds and used zero model calls. No environments or solver trials ran. This is an intake outcome, not a Keel repair success/failure denominator.

Offline inspection of `exclusions-*.jsonl` found 22 unique excluded PRs: 21 had the combined `automatic_acceptance_prerequisite_missing` reason and one had no non-test source change. One of the 21 was docker-py#3185 with a removed test module. The combined reason hides materially different cases.

Inspection of archived GitHub file listings identifies four Celery PRs with actual regression-test files under `t/unit/`: #10290, #10289, #10287 and #9826. These were rejected because the current factory recognizes only top-level tests/test/testing. This is unsupported layout, not absence of tests. GitPython#979 also has tests under `git/test/`, a nested layout outside current support. Merely adding a directory name to admission would be insufficient: freezing, solver write protection, test discovery and acceptance validation must agree before broadening support.

Other sampled titles include GitHub Actions/Poetry installation upgrades and service compatibility changes. Keyword search over popular repositories does not guarantee runnable Python-library regressions. Raising the search cap alone does not address these mismatched prerequisites.

## Proposed evaluation-route adjustment

Keep Keel's roles, shared budget, ledger, recovery and audits. Stop using successful custom environment reconstruction as the prerequisite for every repair-capability experiment. Use a small fixed set of public tasks with existing environment and evaluation specifications, and run model-generated patches through the official external harness. Keep automatic UpgradeBench collection as a separate exploratory effort with explicit environment/intake outcomes.

SWE-bench's official harness provides Docker-based task evaluation and patch prediction inputs:

- https://www.swebench.com/SWE-bench/guides/evaluation/
- https://www.swebench.com/SWE-bench/reference/harness/

Existing `run_swe_public.py` and `run_swe_independent.py` evaluate Compass retrieval; they are not Keel official repair-scoring adapters. An adapter still needs to bind dataset revision and instance IDs, expose only issue/base source to the solver, export the patch, and parse official grading separately from intermediate verification. No official repair adapter or score is claimed here. Repository overlap with prior Compass experiments must be disclosed; unseen-task status cannot be inferred from a new directory.

This is a proposed change to the evaluation route, not replacement of the runtime architecture. No acceptance rules or historical outcomes were changed to create a passing result.
