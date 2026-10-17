# Import-failure preflight and bounded history investigation

The failed Flask-Login transition is preserved. Static inspection of its pinned base now records no direct `from werkzeug.urls import url_decode` import (`.keel/flask-login-import-preflight-v1.json`). The reproduction runner checks this after source verification and before image inspection/building; absent static evidence rejects this specific removed-import hypothesis without more Docker work. Presence is not a reachability or failure guarantee. This gate is specific to the candidate's declared hypothesis, not a universal detector of Python import errors.

To identify the actual historical import removal, a separate bounded read-only tool walks at most 20 file-history commits starting from that immutable base. Patch text is only a search hint. A match requires full pinned source before/after, source blob hash validation, and AST-confirmed import presence followed by absence. All GitHub responses get hash receipts. Missing history or incomplete evidence remains unresolved. This does not automatically change PR 813's baseline, prove the issue relationship, or authorize a benchmark-ready task. GitHub path history across merges is not asserted to be a first-parent-only traversal.

```powershell
python examples/trace_import_fix.py --repository maxcountryman/flask-login --revision e6424a62b3dbdfd789ce6775678c262fa31cbefc --path src/flask_login/utils.py --module werkzeug.urls --symbol url_decode --output .keel/issue-driven-candidates/flask-login-import-history-v1
```

No Docker or paid model calls. The tool environment lacks GitHub API access; use the ordinary terminal. If no removal is found within the bound, retain that result instead of expanding the search repeatedly. A found earlier commit pair defines a new curator investigation and still needs fixed acceptance and actual old/new environment checks; do not reinterpret the old failed experiment as successful. Three tests cover static aliases, pinned removal evidence and corrupt content/bound rejection.
