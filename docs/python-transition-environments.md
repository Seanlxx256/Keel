# CPython version transition environments

The automatic factory can vary either one dependency or Python itself. CPython version tasks are no longer excluded simply because the two environments need different Python versions. Existing dependency recipes without `kind` remain accepted as legacy dependency recipes.

Python recipe example:

```json
{
  "kind": "python",
  "python": "3.12",
  "old": "3.11",
  "new": "3.12",
  "common": ["pip==24.0", "setuptools==68.2.2", "wheel==0.41.3", "pytest==7.4.4", "iniconfig==2.0.0", "packaging==23.2", "pluggy==1.3.0"]
}
```

`python` equals `new`; old and new are distinct supported Python minor versions. The host generates `FROM python:<old>-slim` and `FROM python:<new>-slim` and writes byte-identical requirements. Model-provided Dockerfiles/commands are still prohibited. Exact PyPI pins, including identical pip/setuptools/wheel, are required. Both images run pip check. A version probe verifies actual Python, every requested package and the complete installed-distribution inventory; unexpected packages reject a Python-only comparison. Immutable image IDs and full runtime versions are retained.

A title explicitly requesting Python 3.12 supplies a host hint: the planner cannot silently substitute an unrelated urllib3 transition. The old version still needs metadata evidence; merely observing the title does not establish a historical environment or successful reproduction.

The unchanged frozen acceptance runs on base-old, base-new and gold-new. Identical nonempty JUnit identities and zero skips remain required; only pass/fail/pass enters the solver. The solver receives the new Python image and a Python compatibility goal, without gold source or curator file lists.

## Zero-model-call Docker control

```powershell
python examples/smoke_python_transition.py --output .keel/python-transition-smoke/v1 --execute
```

This builds Python 3.11/3.12 images and exercises SSL socket construction without connecting to a server. It uses a known removed API as a synthetic control: Python 3.12 removed `ssl.wrap_socket`; the supported replacement is `SSLContext.wrap_socket`. [Python 3.12 release notes](https://docs.python.org/3.12/whatsnew/3.12.html#ssl).

The fixture's reference implementation is explicit test data, not an answer injected into Keel. It uses no model calls and establishes no repair score, real-repository success or production TLS validation. The control is separate from automatic candidate discovery and does not change acceptance for collected tasks.

Offline tests verify generated Dockerfiles, identical pin files, actual interpreter checks, extra-package rejection, wrong-axis feedback and solver goal construction. Docker access in the assistant sandbox is denied, so a live container result is still pending. This implementation does not provision external Docker daemons/services, PyPy images or operating-system migrations. docker-py #3185 can now reach Python planning, but its full suite may still need capabilities beyond this factory; no successful reproduction is claimed.
# Dependency resolution update

docker-py-v5 installed model-selected pip 22.3.1 over image pip 25.0.1, then `pip check` crashed inside the old pip on Python 3.12. The next model output repeated the failed recipe. Environment planning now rejects known failed recipe fingerprints before rebuilding, gives up to three bounded correction calls with the original diagnostics, and treats reordered/normalized package names as the same plan. Archived build failures also enter this rejection set. It still stops when bounded corrections or global budgets run out; successful autonomous correction is not guaranteed or claimed. No package version is automatically substituted for a specific task.

The subsequent docker-py-v4 trial spent two outer attempts correcting recipe syntax/missing tooling pins, then failed its only actual build because a selected packaging tool referenced removed `pkgutil.ImpImporter`. No solver ran. EnvironmentPlanner now allows up to three recipe-format calls within each outer environment attempt, retains the original build observation during correction, and charges every call to the existing global budget. Actual build errors therefore still have subsequent outer attempts available. Repeated invalid output remains bounded; authentication/transport failures are not retried by this format loop. Tests cover two invalid recipes followed by a build failure and successful replanning, and global model-budget enforcement. This does not prove live Docker recovery.

The docker-py-v3 live campaign failed before solver execution: attempt 1 included a Linux-incompatible Windows dependency; attempts 2 and 3 omitted transitive packages, finally `cffi`. The previous requirement that the model enumerate the entire dependency closure under `--no-deps` was unnecessarily brittle.

New model-planned Python transitions use pip dependency resolution with exact direct pins. Both images still run `pip check`, verify Python versions and requested pins, and export full installed inventories. The factory requires these inventories to be identical across old/new Python, then writes `resolved-recipe.json` containing all installed exact pins. Successful factory artifacts expose this locked recipe; later reuse verifies the full inventory strictly. Differences return to environment planning with inventory evidence, rather than being accepted as a Python-only transition. Legacy fully pinned recipes and package-axis transitions retain `--no-deps` behavior.

This is package resolution, not OS/service provisioning. It does not establish that docker-py's integration tests can run without a Docker daemon, or that the frozen acceptance is appropriate. No tests were removed or weakened by this update. Live Docker validation remains required.

Reference: [pip dependency resolution](https://pip.pypa.io/en/stable/topics/dependency-resolution/).
