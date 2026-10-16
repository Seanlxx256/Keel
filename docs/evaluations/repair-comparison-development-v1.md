# Feedback comparison: development v1

Source: `.keel/repair-comparisons/development-v1`. Two previously observed development tasks, one run per arm. No held-out tasks or significance claim.

| Task | Repair rounds allowed | Pass | Model calls | Tokens | Runtime seconds |
|---|---:|---|---:|---:|---:|
| Flask-WTF 565 | 0 | yes | 3 | 2638 | 23.891 |
| Flask-WTF 565 | 2 | yes | 4 | 3748 | 30.078 |
| Starlette 2526 | 0 | no | 2 | 1133 | 12.594 |
| Starlette 2526 | 2 | no | 2 | 1135 | 13.578 |

Observed final success is 1/2 in both arms: no observed improvement. All arms executed without environment errors, but both Starlette runs stopped before producing a patch, so feedback recovery was never exercised on that task. Do not silently exclude this upstream failure from end-to-end results.

Flask-WTF without repair passed immediately. With repair, its independently generated initial patch still imported the removed `werkzeug.urls.url_encode`; all four cases failed. One feedback proposal replaced the removed import/use with `urllib.parse.urlencode`, and the same four cases then passed. This shows one additional recovery event, not an improvement over the paired disabled arm. The initial patches differ because model generations are not identical. The enabled arm used 1110 more tokens and 6.187 more runtime seconds in this observation; these differences do not estimate a stable causal effect.

Both Starlette selections included the entire TestClient class at line 418 and transport code at line 239. The resulting proposal input was 27,554 bytes under a 24,000-byte limit. Selecting the constructor separately did not help when its enclosing class was already selected. Raising the retry limit cannot fix a failure before the first patch request.

Next engineering priority is budget-aware localization: expose definition sizes, detect redundant ancestor/descendant selections, and allow bounded refinement to smaller definitions before patch generation. Preserve full selected definitions and explicit omission metadata; do not silently truncate code or insert the known task fix. Validate capacity offline before another paid run. Larger context caps remain an experimental alternative, not evidence that recovery itself works better.
