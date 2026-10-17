# Flask-Login issue 5279: explicit historical range

Import history identifies `abab0cbf5fd3f172a26e710b5326790d5703f334` immediately before `7b170bf4e5e0240fe084166c9ca6ec4fba258dcd`, which removes the actual Werkzeug URL imports. Hash-verified API source confirms presence before and absence after. However, that initial fix uses parse_qs without keep_blank_values=True, which is statically inconsistent with the existing blank-query acceptance requirement. Its runtime behavior has not been executed here.

Do not remove that requirement to force acceptance. A separate historical-range experiment starts at the verified pre-import-fix base and ends at the already probed official release merge `e95b034ed173b0fcdcaee48b3b82f68e70053e50`. This is explicitly not PR 813's adjacent first-parent pair and does not change the earlier rejected result. It spans multiple official changes and is curator-selected after inspecting prior outcomes; no independent or representative benchmark claim is appropriate.

The new runner reuses the exact original five-case PROBE, cases, dependency pins and strict three-cell assessment. Before Docker execution, it verifies a bounded GitHub comparison: status ahead, base and merge-base equal the fixed old commit, at most 20 commits, bounded file list. Actual byte-inventory changes must exactly match the recorded comparison paths. The old source must still contain the reported import. Invalid ancestry, missing source, unrelated runtime failures or the known old/new-baseline failure pattern remain failures.

```powershell
python examples/reproduce_flask_login_issue5279.py --history .keel/issue-driven-candidates/flask-login-import-history-v1
```

Existing dependency images are reused; no --build-images is needed. GitHub ancestry metadata and the earlier base snapshot may require downloading. The current official gold snapshot is reused. No model calls. Three tests cover unchanged acceptance, valid ancestry and rejection of divergent/unbounded metadata. Offline history replay succeeded; the new real three-cell experiment is still pending. Retain its result even if it fails.
