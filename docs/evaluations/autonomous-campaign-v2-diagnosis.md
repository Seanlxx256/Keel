# Automatic campaign v2: environment protocol, not a repair trial

Artifact: `.keel/autonomous-campaigns/new-repos-v2`.

Six repositories were searched. One metadata-eligible candidate reached the factory: docker/docker-py #3185, titled "breaking: Python 3.12 compatibility & remove custom SSL adapter". No solver ran. The campaign used 3 model calls, 7,662 reported tokens and 347.515 seconds overall.

All three factory attempts failed during recipe validation, before any Docker build:

1. The response mixed pinned dependencies with bare names/ranges and placed the target distribution in common pins.
2. The response returned a JSON Schema wrapper rather than a recipe instance.
3. The response combined schema fields with recipe fields and still duplicated the target distribution.

Calling this an image-build failure would be incorrect. No old/new/gold execution or Keel repair outcome exists.

There is also a task/factory mismatch: this PR title explicitly describes a Python-version transition, while this factory holds Python fixed and varies one external dependency. The proposed urllib3 pair is not verified transition evidence. Python/runtime-version tasks are now conservatively routed out before paid environment planning; this does not claim the upstream issue is unsolvable or that Python transitions are implemented.

Generic corrections provide field-specific validation errors, the previous rejected response as bounded untrusted feedback, an explicit instance-versus-schema instruction, and per-attempt stage reporting. Tests exercise invalid pins, schema confusion, correction within one shared budget and rejection of unsupported transition kinds before planning. Raw prior responses and original campaign results remain unchanged. No new live success is claimed.
