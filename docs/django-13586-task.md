# Django 13586 task and first trial

Successful reproduction: `.keel/upgradebench-reproduction/a950f72c7e9e46d78798e7025297939d`. Export: `.keel/task-packages/django-13586-v1`. The exporter requires the matching runner/probe hashes, pinned revisions/images and exact three-cell assessment. Task JSON deliberately excludes gold revision, PR body, diff and curator file list. The model receives only the goal plus actual bounded baseline case errors; acceptance code is executed by the host, not copied into the goal.

The generic package runner now explicitly supports the two known package identities (HTTPX and Django), resolves snapshots by repository, validates the declared source prefix, and checks the expected baseline error type from the Django manifest. Both wrong dependency versions and unrelated failures reject the baseline. Final success still requires runtime audit success, nonempty scoped changes, Docker acceptance, exact case/version records and real model calls.

The initial Django model trial uses localized-proposal with a 48,000-byte cap, two verification repair rounds, existing shared 450-second/30-model-call/60-tool-call/180,000-token budget and no installed-contract selection. The larger cap is fixed before model execution because the base repository's 860 non-test Python paths alone occupy about 34 KB. This is an input-cap choice, not a measured benefit or an equal-configuration comparison with earlier 24 KB development tasks.

```powershell
python examples/run_transition_task.py --output .keel/transition-trials/django-13586-first --execute
```

This remains a first model attempt on a newly packaged but curator-inspected task. It is not an independently audited held-out benchmark. The existing probe tests one instrumented callback scheduling contract, not all changed Django handlers, real static file serving, database thread affinity or the upstream full suite. Success must not be described as full asgiref compatibility. Failure is retained, and outcome-driven runtime changes would turn this task into development data.
