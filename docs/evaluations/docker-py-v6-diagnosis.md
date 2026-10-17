# docker-py v6: environments built, acceptance invalid for the current factory

The archived `docker-py-v6` campaign built images and ran all three cells twice. No Keel solver invocation occurred. All cells exited 2 during pytest collection, rather than demonstrating a valid old-pass/new-fail/reference-pass transition.

Two independent blockers are visible in saved executions:

- `tests/integration/client_test.py` constructs a Docker client during collection. The isolated verifier has no Docker daemon socket, so both source revisions fail fetching server API version. Installing more Python dependencies does not provide that service.
- `tests/unit/ssladapter_test.py` imports `ssl.match_hostname`, unavailable in the target Python. This module exists only in base; the upstream reference deleted it. Our frozen union restored it into gold, so the reference also fails collection. This is acceptance construction incompatibility, not a model repair failure.

The frozen union intentionally preserves base-only tests to avoid silently weakening acceptance, but that conservative rule is not suitable for every API-removal migration. This task needs an explicitly reviewed acceptance policy and service requirements before further agent evaluation. Choosing a unit-only scope or accepting upstream test deletion after observing results would create a new evaluation definition, not turn this failed attempt into a pass.

The factory now detects removed upstream test modules before model calls/builds and returns `acceptance_review_required`, listing paths. This is a static capability boundary, not proof that tests should be deleted. Campaigns retain the record and continue other candidates. No tests, Docker isolation controls, or historical results are modified.

Local preflight on the archived source snapshots confirmed the removed module. Unit coverage verifies the review classification happens before planner/build invocation. Live Docker behavior after this change is not claimed; the recorded Docker results are the user's prior v6 execution.
