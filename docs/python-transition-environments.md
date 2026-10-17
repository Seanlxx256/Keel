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
