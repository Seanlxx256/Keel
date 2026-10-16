# Feedback comparison: development v2

Source: `.keel/repair-comparisons/development-v2`. Same two known development tasks, new size-aware localization implementation, one run per arm. No held-out coverage.

| Task | Repair disabled | Repair enabled |
|---|---|---|
| Flask-WTF 565 | verification failed, 3 calls / 2672 tokens | repair proposal rejected, 4 calls / 3924 tokens |
| Starlette 2526 | passed, 3 calls / 6186 tokens | localization still oversized after refinement, 3 calls / 2358 tokens |

Observed success is 1/2 disabled and 0/2 enabled. Initial localization and patches vary across provider generations; this small diagnostic does not establish that feedback harms success. It also does not demonstrate improvement. Keep all failures in the report.

The Flask-WTF enabled arm exposed a host inconsistency: focused repair evidence contained widgets.py only, but the prompt's allowed files still included validators.py. The model generated edits for both, including validator snippets not established by current evidence. The validator accessed a shadow-source entry that had never been loaded, yielding a KeyError reported as an invalid patch. This is partly an interface defect, not purely a model error.

Correction: proposal requests and application validation now use the intersection of original declared files and unique current evidence paths. Evidence cannot introduce undeclared files. An edit outside this current evidence scope raises an explicit policy denial before any batch write. It does not silently read missing files, expand scope, or assume a fabricated snippet is valid. To edit an omitted file later requires explicit evidence acquisition in a future design. Three new regression tests plus 27 existing proposal/localization/recovery tests passed; no new live success is claimed.

Starlette's disabled arm shows a feasible localization can pass, while the enabled arm failed before patching despite one refinement. Size hints are advisory and one refinement is not sufficient in every generation. Preserve this outcome rather than repeatedly changing prompts against the same case. Next evaluation should stabilize evidence/tool contracts and add unseen tasks; additional repeats on these cases are diagnostic only, not independent coverage.
