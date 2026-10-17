# Flask-Login first trial: localization protocol failure

Artifact `.keel/transition-trials/flask-login-issue5279-first`, prepared hash `933f744ac79ca142869ef17f572a6d6ecf5fcbd61b24c6a68ac86deaace5f194`. This is an actual failed Keel trial: two model calls, 2052 reported tokens, four tool calls, 14.328 seconds, no edits and no final acceptance execution.

The selected files were package init, login_manager and utils. The model returned eight locations including `src/flask_login/__init__.py:11`, an observed traceback import line rather than a definition start shown in the catalog. The whole selection failed exact-ID validation. Most returned utils positions were valid; they were not enough to override the invalid entry. A traceback source frame is useful diagnostic evidence, but is not itself an editable definition ID.

Correction: localization's existing single additional selection opportunity now also handles invalid IDs. The model receives the invalid IDs and a requirement to return a corrected complete selection from the same displayed definition catalog. The host neither maps arbitrary lines to nearby definitions nor silently drops bad entries. The correction and capacity refinement share the same two-selection limit and global budget; repeated invalid output stops without writes. File selection and unrelated schema/provider errors are not covered by this change.

Three new fixture tests cover correction, repeated failure and budget enforcement; eleven existing localization and three size-refinement tests also passed. This is protocol recovery evidence, not real task success. After inspecting this first failure and changing the protocol, Flask-Login is registered as development data; the historical task is linked to PR 813 for exposure tracking only, not misrepresented as its immediate first-parent range.

Fresh follow-up `.keel/transition-trials/flask-login-issue5279-location-feedback-v2` starts from original base, with unchanged package, probe, images, context cap and shared budgets. No model calls occurred during preparation. Preserve the first failure.

```powershell
python examples/run_transition_task.py --output .keel/transition-trials/flask-login-issue5279-location-feedback-v2 --execute
```
