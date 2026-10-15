# Starlette #1936: compatibility candidate review

Status: selected-environment Docker probe reproduced; not a ready benchmark task.

## Recorded live result (2026-10-15)

## Exploratory Keel task export

Prepare without model calls or Docker access:

```powershell
python examples/run_starlette_upgrade_task.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9
```

Run a fresh export with the CPU Ollama agent and Docker acceptance:

```powershell
python examples/run_starlette_upgrade_task.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9 --execute
```

The exporter verifies clean pinned snapshots, the raw gold commit's first-parent
header (works with shallow fetches), and the exact changed-path set across both
complete snapshots. The actual cached pair passed these checks. The base copy
contains no `.git`, gold tree or reference patch. Curator inventories and hashes
are written outside the agent workspace. The runtime receives the task goal and
base tools; acceptance is trusted host configuration, not a reference answer.
This is application-level separation, not host filesystem isolation.

The goal provides the observed error and affected filename, so this is a repair
task with supplied localization, not an independent Compass retrieval evaluation.
Execution first rechecks the base failure in the resolved image, then runs Keel
with CPU offload disabled, context 4096 and a 900-second runtime budget. Final
success requires runtime audit success, real model calls, only the expected file
changed, and matching probe cases/versions passing. Different correct patches
can pass; byte equality with gold is not required. The filename restriction is
in the goal and post-run assessment, not an additional runtime permission grant.

Prepared artifact: `.keel/upgradebench-agent/aef8f5d423db452d98aa91c07d201359`.
No live model run or resolve result has been established yet. Four reproduction
tests cover evidence assessment, task-answer separation and range checks.

## Live Docker evidence

## First agent failures and protocol correction

The bounded 450-second, five-turn-per-role attempt at
`.keel/upgradebench-agent/55e49f5394dc474d9cb7c285c5b0074b` reached Verifier after
11 model calls with no file changes. Acceptance correctly failed on the unchanged
source. Archived decisions show Planner proposing `anyio.run_blocking`, a name
not supported by the supplied evidence; Implementer searched for it, found no
match, then returned a proposed change rather than performing it. This is a
model planning/action failure, not a successful compatibility implementation.

The last-turn provider schema also forced a final answer once evidence had been
observed. That coercion is removed: a tool action remains possible on the last
turn, and a session that uses its last turn without finishing reports budget
exhaustion. Ordinary explicit finals still reach independent verification; no
automatic patch or mandatory edit is injected. Agent tests cover both the last
tool-turn failure path and a valid voluntary final. The task runner also exposes
`--model` to select an existing Ollama model for a future controlled comparison;
it does not download models or change the current model automatically.

The attempted task remains unresolved. Further repeated runs of the same model
should not be presented as benchmark progress; preserve these failures and
separate runtime fixes from evidence of repair capability.

A further run (`.keel/upgradebench-agent/b25bbc482025458cad021606171a8c78`)
again made no edits and timed out after 22 model calls. Repeated preview
suppression reduced prompt growth (Implementer input reached 17,134 bytes rather
than 38,035), but the model kept selecting `read_file` despite the hints. No repair
progress was established; adding a tool alone did not fix action selection.

The session now pauses full-file reads after an actual unchanged repeat, removes
that tool from subsequent provider schemas, and rejects the same action from
unconstrained providers. Search, bounded line reads and recall remain available.
A successful edit restores full-file reads. Both strategy transitions are traced;
this is a deterministic loop intervention, not a learned early-stop predictor.
It does not force a specific patch or imply all repetitive behavior is solved.
Twenty agent tests and six gateway tests pass, including a complete structured
read-repeat/window/edit/verify test and schema restoration after the edit.

For a bounded live diagnostic rather than another default 15-minute run:

```powershell
python examples/run_starlette_upgrade_task.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9 --execute --max-seconds 450 --max-steps 5
```

The 450-second limit covers agent runtime, not snapshot preparation or baseline.
The five-turn limit is per role. A short-budget failure remains a failure, not a
discarded result; compare with earlier runs only while reporting changed limits.

The next live run (`.keel/upgradebench-agent/6204c980effe452bbfce131a448a64d6`)
used 18 model calls, changed no files and timed out in Implementer. Its trace
shows six identical `read_file` calls in that role, increasing prompt input to
38,035 bytes despite cache hits. Repeated file-prefix delivery, not file I/O,
was a concrete context bottleneck. A 4096-token provider context may also lose
earlier instructions as that history grows; this is an inference, not a measured
provider truncation trace.

The gateway now exposes `read_lines(path, start_line, end_line)` to all existing
agent roles, with at most 80 lines and 3000 source characters per response.
Search hits can guide direct reads near late-file call sites. Responses include
line bounds, source hash and continuation line. These window facts count as
observations but are not implicitly shared through full-file handoff metadata.
Repeated full-file reads in the same session still perform fresh content checks
and consume tool budget, but return the existing fact reference and guidance
instead of another identical preview. Changed content yields fresh evidence.
This bounds duplicate read output; it does not compact all conversation history
or force a model to make progress. Live success remains unproven.

The first live agent attempt failed to load the model (CPU_REPACK allocation).
The subsequent attempt at `.keel/upgradebench-agent/ee7b4af988644705a09a1d3d1d5cefd6`
reached Implementer, used 15 model calls and changed no files. Ledger facts
17/19/21 show truncated JSON followed by two invalid `replace` argument objects;
the final request timed out near the 900-second runtime deadline. This is not
evidence of an independent short HTTP timeout or failed Docker acceptance.

The provider tool schema previously constrained the tool name but allowed a
generic argument object. It now emits a separate branch per available local tool,
with required argument names/types and no extra fields, using the same contracts
as the gateway's runtime validation. Namespaced MCP arguments retain their
existing independent validation boundary. Implementer guidance requests short,
unique edits and targeted searches rather than reproducing long file contents.
Gateway checks remain authoritative; schema constraints do not authorize writes
or guarantee complete responses within an output-token limit. No automatic
repair or hidden reference patch is injected. A new live run is still needed.

User-executed artifact:
`.keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9`.
The saved executions were independently re-evaluated using `assess()` and passed
its evidence checks. Both base cases (`request`, `lifespan`) exited with the
expected `AttributeError` for missing `anyio.start_blocking_portal`; both gold
cases passed with exit zero. Neither execution timed out; stderr was empty.
Recorded dependency versions match the eight selected version pins exactly.

- Image ID: `sha256:47866eb38009a0bfa104f074399288e467fb98eeec5e04b016184352dcd62a4f`
- Probe SHA-256: `445ce86286be2c46ecde9cb7fa526b36c27ec3811f249287f8432dcb25100f8c`
- Environment: released AnyIO 4.0.0, not the original unreleased upstream commit.
- Outcome: one reproduced compatibility candidate; zero benchmark-ready tasks.

This establishes an actual API incompatibility in the chosen environment,
not merely an installation failure. Pending work: local Git range verification,
a frozen portable acceptance/environment bundle, leakage-reviewed agent task,
independent review, and a real Keel run. The two probe cases are not a full
upstream regression suite or two independent benchmark tasks.

## Runnable selected-environment probe

```powershell
python examples/reproduce_starlette_1936.py --build-image
```

This explicitly selects released AnyIO 4.0.0 rather than the author's unreleased
commit. It builds a Python 3.11 image with exact runtime package versions and
`pip check`, records the resolved image ID, prepares clean exact Git snapshots,
and runs the identical two-case request/lifespan probe on each revision. Both
containers use the same image ID, nonprivileged user, read-only mounts and no
network through the existing verifier runner. Image build and Git preparation
need network; acceptance does not. The build installs historical dependencies
only in this dedicated image; they are not project dependencies.

Image tags and package indexes are mutable inputs: version pins alone are not a
hash-locked environment. The resolved image ID identifies this run's environment;
it is not a portable image archive or independently reproducible image digest.
Run without `--build-image` to reuse the image; `--offline` additionally requires
cached snapshots. No agent/model is called.

Artifacts under `.keel/upgradebench-reproduction/<id>` contain image build and
inspect logs, base/gold executions, package versions and summary. `probe_passed`
requires both base cases to fail with the expected missing AnyIO API, both gold
cases to pass, exact dependency versions and case identities, and proper exit
codes. Timeouts, installation/import errors and unrelated test failures do not
count. `benchmark_ready` remains false even if this narrow probe succeeds.

The agent's initial execution could not access the Docker engine named pipe;
failure evidence is saved under
`.keel/upgradebench-reproduction/0a2776f8bc0c4b988a748f94f450d928`.
That initial attempt established no live result; the successful user run above
supersedes it. Two automated assessment tests
cover success and rejection of invalid evidence.

## Archived evidence

- Repository: `kludex/starlette`; PR: https://github.com/Kludex/starlette/pull/1936
- Base (merged commit first parent): `fbab16a2b114321c1694788b21113bbba8943778`
- Gold merged commit: `a45027209ae4c033007d827a37bbbee53550973a`
- Changed file: `starlette/testclient.py`.
- Source archive: `.keel/upgradebench-mining/0b9336d864ae470e8a9ac5cd08d8a092`.
- Schema v3 replay: `.keel/upgradebench-mining/4c363ce8c3e04fec820df75f7022b97d`.

The archived PR description identifies an unreleased AnyIO change at commit
`9f97cd7bb5f59f79f1bcda64230ab2127e79935a`. This is an upstream dependency
revision cited by the author, not a locally verified reproducible dependency.
The archived patch imports `anyio.from_thread` and replaces two calls to
`anyio.start_blocking_portal` with `anyio.from_thread.start_blocking_portal`.
This is a concrete API-location change, making the PR worth reproducing.

Strict screening still rejects it: fewer than three changed files and no
dependency manifest change. The separate compatibility pool retains it for
review without changing strict eligibility or benchmark denominators.

## Required reproduction gate

1. Verify the local base-to-gold Git range and changed paths against receipts.
2. Resolve the cited AnyIO commit, Python constraints and a complete frozen
   dependency environment. Do not substitute current package versions silently.
3. Build a trusted acceptance bundle exercising TestClient lifespan/portal
   behavior, with the same tests and dependencies for base and gold.
4. Run both revisions in Docker; require an actual API incompatibility failure
   on base and passing acceptance on gold. Installation errors are not evidence.
5. Record test identities, execution metadata, image identity and logs. Review
   agent-visible instructions separately so the gold patch stays curator-only.

Clean exact snapshot checks, image build and base/gold execution are now recorded
for the selected environment; completed manual acceptance review and full Git
range verification remain pending. #2400 also enters the metadata review queue,
but its broader ASGI compatibility title alone does not establish an external
dependency-upgrade task.
