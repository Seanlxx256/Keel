# HTTPX context grid v1: observed failure

Source: `.keel/transition-grids/httpx-context-v1`. One known development task, three cap settings, one run per setting; no held-out tasks.

| Cap (bytes) | Maximum actual input (bytes) | Tokens | Runtime seconds | Acceptance |
|---:|---:|---:|---:|---|
| 12000 | 11203 | 6097 | 30.406 | failed |
| 24000 | 11857 | 7373 | 31.344 | failed |
| 48000 | 11203 | 6283 | 28.563 | failed |

All arms made four model calls and produced the same source patch: rename pool request methods to `handle_request` / `handle_async_request`, and rename `ext` to `extensions`. All four acceptance cases in every arm then failed with `AttributeError: 'bytes' object has no attribute 'encode'` in `ensure_http_version_reason_phrase_as_bytes`.

This is progress past the original missing-method failure and the previous unexpected-keyword failure, not a successful repair. The remaining observed error is in response extension conversion. API signatures helped with call shape but did not establish the return-value representation or the compatibility helper's assumptions.

Every actual request fit below the smallest cap. Therefore this grid shows no benefit from relaxing the cap on these generated requests; it does not compare the quality of 12/24/48 KB evidence payloads. Upstream model selections varied and were not a frozen candidate replay. Single-run timing/token differences cannot establish a cap effect.

Next priority is a generic bounded verification-feedback repair cycle: return concrete final errors with current-source evidence to the model under the same global budget, preserve failed attempts, and rerun unchanged acceptance and audit. Include helper definitions relevant to the new traceback and permit inspection of dependency implementation/return contracts, instead of inserting a task-specific fix. This cycle is a proposed next step, not implemented by this report. Preserve this grid without rerunning or overwriting it.
