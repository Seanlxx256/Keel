# Django 13586 dependency transition probe

Fixed selected candidate: django/django PR 13586, base `0b4fe82c7405ba96f2eb25b954a8f498cc8364b3`, gold `e17ee4468875077b90b70bb6a589ebad7493f757`. Inputs come from the completed fixed shortlist; the runner verifies registry/selector hashes, recomputes selection, checks snapshots and first-parent ancestry, and compares changed paths with archived PR metadata. Curator patch inspection was used to design this probe; none of these curator inputs constitutes a model repair run.

The observed dependency transition changes sync_to_async's default scheduling. The candidate probe exercises Django's real StaticFilesHandlerMixin.get_response_async with an instrumented serve callback. Two callbacks rendezvous at a barrier and return distinct HTTP response bodies. It tests concurrent dispatch of a thread-independent callback, not actual disk serving or an upstream full-suite failure. The bounded barrier timeout is a scheduling observation, not a throughput measurement. If this distinction is not sufficient for the intended task, keep benchmark readiness false and obtain upstream acceptance coverage.

Three required cells use Python 3.9, pytz 2020.1, sqlparse 0.4.1 and asgiref 3.2.10 / 3.3.0: base-old must pass, base-new must fail specifically with BrokenBarrierError, gold-new must pass. Import errors, dependency mismatch, missing cases or container timeout cannot substitute for the expected transition failure. Image IDs, inventories, versions, raw executions and hashes are saved. These historical environment pins are a reconstruction, not proof of the exact original upstream environment.

```powershell
python examples/reproduce_django_13586.py --collection .keel/independent-candidates/f605261034134a3b87677fd4a2ffcd7f --build-images
```

The first tool-environment attempt saved `.keel/upgradebench-reproduction/d75e5bfa83e04c399c467bd2cca36c60`; image building failed with access denied on `C:\Users\Admin\.docker\buildx\.lock`. No probe cells ran and no model calls were made. Run the command in the ordinary user terminal, retaining this failed environment attempt. Three offline tests cover assessment gates and probe compilation; they do not establish a successful real reproduction. Even if all three cells pass, this remains a curated one-case probe until task packaging and wider acceptance are validated.
