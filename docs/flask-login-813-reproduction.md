# Flask-Login 813: issue-driven reproduction

Hash-verified candidate: `.keel/issue-driven-candidates/flask-login-813-v2`, collected from the explicit issue/fix pair. The runner reconstructs candidate metadata from response receipts, verifies the fixed merge and first parent, checks raw snapshot cleanliness and actual changed paths, and never selects a replacement candidate.

Fixed base: `e6424a62b3dbdfd789ce6775678c262fa31cbefc`; gold: `e95b034ed173b0fcdcaee48b3b82f68e70053e50`. The source diff removes the URL helpers no longer exported by Werkzeug and changes URL parsing/encoding. Upstream test edits also adapt to newer cookie-client APIs. This is executable source change, unlike the excluded Sphinx type-comment candidate. Regression coverage from the upstream full suite has not yet been executed.

Reconstructed images use Python 3.11 and Flask 2.3.3, Jinja2 3.1.2, MarkupSafe 2.1.3, itsdangerous 2.1.2, click 8.1.7 and blinker 1.6.2. Only Werkzeug changes: old 2.3.7 versus new 3.0.0. These are experimental pins, not a claim to exactly reproduce the issue author's environment/version statements. Package installation uses --no-deps followed by pip check.

The identical probe covers import, repeated/blank login query values, same/external-host next URLs, signed-cookie roundtrip/tamper rejection and a local login/protected/logout session flow. It imports checkout source via /workspace/src and asserts the source origin. This is five curated cases, not a full auth security or upstream test-suite validation. Three cells are required: base-old passes, base-new fails specifically on the removed url_decode import, gold-new passes. Wrong versions, unrelated import failures and timeouts reject the transition.

```powershell
python examples/reproduce_flask_login_813.py --candidate .keel/issue-driven-candidates/flask-login-813-v2 --build-images
```

Three offline tests passed for assessment gates and probe compilation. The first tool attempt saved `.keel/upgradebench-reproduction/d16bd163091c40f3bee135c440b74537` and stopped building the old image because Docker buildx's user lock was inaccessible. No real probe cell or model request executed. Run the command in the ordinary user terminal. Preserve this environment failure. Do not package a repair task until the three-cell result is actually validated.
