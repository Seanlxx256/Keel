# aiohttp 9316 curator review

Fixed selected candidate from collection `f605261034134a3b87677fd4a2ffcd7f`. Archived PR body and file response hashes were verified before inspection. Review artifact: `.keel/candidate-intent-review/aiohttp-9316-v1/review.json`.

The old client request code computes whether yarl >=1.13 and already uses `URL.host_subcomponent` in that branch. The PR removes the version import, guard and old-version fallback, leaving that same newer branch unconditional. The PR body says the minimum version had already been raised and warns against backporting to an older branch requiring old yarl. Tests remove explicit exercises of the obsolete branch.

Decision: do not proceed to a repair-agent trial without a demonstrated base failure. This is a source-based compatibility-cleanup assessment, not an executed proof of semantic equivalence or of base behavior. No Docker cases or model calls ran. Do not manufacture a test that checks deletion of a particular symbol simply to make the old code fail: that would measure matching the PR rather than fixing a user-visible regression.

Preserve this candidate and its deferral; do not silently promote a reserve from the same fixed cohort. The other selected candidate, Django 13586, passed a curated reproduction, then became development data after model failure diagnosis and an outcome-driven handoff correction. Neither outcome establishes an independent repair score for this cohort.

A separate discovery policy (`independent_candidate_policy_recovery_v2.json`) excludes all registered development repositories. It is a new cohort, not a retroactive replacement. Previously collected Jinja/Sphinx metadata is disclosed; exact future task exposure still needs review. Keep current runtime behavior fixed before inspecting new repair outcomes.
