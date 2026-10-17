# Flask-Login PR list versus merge first-parent delta

Actual pinned snapshots have five changed files: CHANGES.md, requirements/ci-tests.txt, requirements/tests.txt, src/flask_login/utils.py and tests/test_login.py. The archived PR API lists eleven paths. The gold commit is a two-parent merge with the declared base as its first parent. All six additional advertised paths are present and byte-identical between these fixed pins. The PR list and first-parent delta are different comparison scopes; exact list equality was too strict for this merge.

The runner still requires the same immutable base/gold commits and verified first parent. It now requires a nonempty actual delta contained entirely in the archived PR paths, verifies every omitted advertised path exists on both sides and has identical content, and requires a library-source change. Any unadvertised changed path, missing omitted path or metadata-only delta rejects the range. It records the unchanged advertised paths and merge parent IDs. No commit or acceptance probe was changed to obtain a pass.

Offline validation confirmed five actual changes and six unchanged advertised paths. Three range regression tests, three transition assessment tests and two explicit issue-pair tests passed. Existing images and snapshots can be reused:

```powershell
python examples/reproduce_flask_login_813.py --candidate .keel/issue-driven-candidates/flask-login-813-v2 --offline
```

The tool-environment offline attempt saved `.keel/upgradebench-reproduction/86d77d4c7ebc463c94a05d2d1fd0586f` and was blocked at Docker image inspection by daemon access permissions; no probe cells ran. Run in the ordinary user terminal. Old failed reports remain unchanged. This correction validates source provenance only; real three-cell behavior is still pending.
