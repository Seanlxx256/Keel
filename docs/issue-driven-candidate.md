# Issue-driven candidate: Flask-Login 813

Discovery references:

- https://github.com/pallets/flask/issues/5279 reports an ImportError from flask_login importing url_decode after a Werkzeug upgrade. Its reported versions are user text, not validated pins; do not copy them unquestioningly into Docker requirements.
- https://github.com/maxcountryman/flask-login/blob/main/CHANGES.md associates Flask/Werkzeug 3 compatibility with PR 813 and release 0.6.3.

This provides a concrete reported failure and a lead to a fix, unlike a compatibility title alone. The PR itself, issue linkage, regression tests, pinned commits and old/new environment still require validation. Neither reference establishes that our runner can reproduce the failure or that the PR fixes every reported symptom. This is a curator-selected candidate, not random sampling or independent success coverage.

`examples/prepare_issue_candidate.py` collects exactly the explicit issue and PR. It verifies merged status, commit identity, first parent, bounded complete file listing and repository resolution; it stores hash receipts and keeps gold/PR file metadata curator-only. It does not search for replacements, create a model task or infer readiness. Two fixture tests cover verified metadata and rejection of unmerged/mismatched/incomplete inputs.

```powershell
python examples/prepare_issue_candidate.py --repository maxcountryman/flask-login --pr 813 --issue-repository pallets/flask --issue 5279 --output .keel/issue-driven-candidates/flask-login-813-v2 --execute
```

The tool environment attempted the initial public metadata request under `.keel/issue-driven-candidates/flask-login-813-v1` but network access failed after bounded retries. Keep that attempt. The command above runs in the user terminal, makes only read-only GitHub requests and no paid model calls. Source review is the next gate; do not automatically proceed to inference.
