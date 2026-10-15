# Starlette #2526: second curated compatibility candidate

Source: https://github.com/Kludex/starlette/pull/2526
Merge: https://github.com/Kludex/starlette/commit/a4cd0b5506ac2fd3fa0ce1e967f019b94df87b97

Pinned first parent: `7533b61a34f8b0dcb5fc35c717d458439f0baf18`.
Pinned gold: `a4cd0b5506ac2fd3fa0ce1e967f019b94df87b97`.
The upstream diff changes only `starlette/testclient.py`. The original PR
addressed HTTPX 0.27's deprecation warning. This experiment deliberately targets
released HTTPX 0.28.1, where the old parameter is removed, to obtain a concrete
base failure. It does not reproduce the original upstream dependency environment.

## Reproduce before paying for a model call

With Docker Desktop running:

```powershell
python examples/reproduce_starlette_2526.py --build-image
```

This downloads pinned Git snapshots and builds a dependency-only image. No
model credentials or inference calls are needed. The image uses a Python 3.11
base tag, eight exact dependency versions, `--no-deps` and `pip check`. The
resolved local image ID identifies this run; dependencies are not wheel-hash
locked, and the base tag is not a portable immutable image archive.

The script checks clean snapshots, first-parent identity and exact changed-file
inventory before executing four independent acceptance cases: plain request,
lifespan context, redirects and cookie propagation. Both snapshots run with the
same image in the existing nonprivileged, read-only, network-disabled verifier.
Acceptance requires all four base failures to be the expected constructor
TypeError, all four gold cases to pass, and exact package-version equality.
Missing cases, unrelated failures, timeout or mismatched dependencies are rejected.
The probe remains curator-authored, not the full upstream test suite.

Inspect `summary.json` under the printed artifact directory. Only if
`probe_passed: true`, prepare a fresh base-only model task using that directory:

```powershell
python examples/run_agent_baseline.py --case 2526 --reproduction REPRODUCTION_DIRECTORY --strategy proposal --group real_compatibility --model-config .keel/model-openai.json
```

Add `--execute` for the paid model run. This task does not support
`--dependency-evidence`; its proposal windows use source query anchors supplied
by the host. Gold revision and gold patch stay outside the model workspace and
prompt. The task gives the affected filename, so this is localized repair, not
Compass retrieval evaluation. Goals/acceptance are fixed before the first model
attempt; preserve all failed attempts rather than silently revising the task.

## Status and limits

Docker reproduction passed on 2026-10-15 in user-side execution. Saved artifact:
`.keel/upgradebench-reproduction/a5a65d40fa92407aa5ec9861910988d3`.
All four base cases failed with the expected constructor TypeError; all four
gold cases passed, with matching pinned dependencies and no timeouts. The saved
summary was also accepted by the local assessor. Image ID:
`sha256:2599e344e3f3e9b64721f6fb47428445c50ddf273b0a10e266418e4ff65eb73b`.
Probe SHA-256: `1506a6fe4f360e2a91683bb2f926445998af7a1bf43d09165b406ca9560215f3`.
Summary SHA-256: `1ef68c1a5f113d4e8c51bb3dcc73113ca9c8d7f7d7236e68054f0b4bbc5f761e`.
Base-only proposal preparation succeeded at
`.keel/agent-baseline/2b0f0bb0b27a4bc7ac74462401eb6005`, without model calls.
First inference attempt after source-context preflight passed on 2026-10-15:
`.keel/agent-baseline/4f8fc847d3164f5d84f2b2d2934dc950`.
The saved runtime result, patch and baseline/final acceptance were inspected.
The patch removes only the obsolete `app=self.app` argument at the parent
constructor call in `starlette/testclient.py`. All four final cases passed with
the reproduced package versions; the assessor accepted the saved base/final
pair. Audit reported exactly the declared file changed and no findings.
JUnit identity checking was not enabled; this is the curated JSON probe.
Requested model: `gpt-5.4-mini`; reported model:
`gpt-5.4-mini-2026-03-17`. One model call, 1106 reported tokens, 3897 input
bytes, 10.406 runtime seconds and 20.125 seconds including baseline. No protocol
or failed gateway calls were recorded. This is one observed repair, not a
resolve-rate estimate or proof of runtime superiority. All artifacts remain
`benchmark_ready: false`.
The first executed harness attempt at
`.keel/agent-baseline/855d721d02ed456680224b904f1a063b` failed before inference:
the broad `httpx` anchor selected many type annotations, exceeding the 12000-byte
input limit. Model calls and tokens were both zero. Preserve this failed attempt;
it is a task-preparation defect, not an observed model repair failure.
Anchors were narrowed using base source and the reported constructor error to
`class TestClient(` and `super().__init__(`, without gold replacement text.
The shared source-window/request builder now checks source context during
preparation and records its size. Runtime still checks the final request,
including optional dependency evidence. New preparation at
`.keel/agent-baseline/a90f579ae24340fc8625b377300afedc` reports 3897 input bytes
against the unchanged 12000-byte cap. This task has now undergone harness
debugging and must not be described as untouched held-out evaluation.
This is a second PR but the same repository and TestClient subsystem as #1936;
it provides limited additional task coverage, not cross-repository generalization.
Neither task should be treated as held-out after iterative debugging. Broader
evaluation still needs additional repositories and manually reviewed tasks.
