# HTTPX package trial

`examples/run_transition_task.py` prepares a fresh base-only workspace and then
executes the existing six-role tool loop. It does not supply curator file
localization or a gold patch. This is not the operator-localized proposal
strategy and is not an independent benchmark score.

Preparation performs no model or Docker calls:

```powershell
python examples/run_transition_task.py --package .keel/task-packages/httpx-1588-v1 --model-config .keel/model-openai.json --output .keel/transition-trials/httpx-1588-first
```

That directory has already been prepared in this workspace. Execute it once:

```powershell
python examples/run_transition_task.py --output .keel/transition-trials/httpx-1588-first --execute
```

The prepared manifest binds implementation, task configuration, copied base
inventory and verifier acceptance. Model configuration uses environment-based
credentials, not embedded keys. Runtime budget: 450 seconds, 30 model calls,
60 tool calls, 180,000 tokens, 12 turns per role, 12,000 context bytes and 1,024
output tokens per call. Baseline verification has a separate 90-second timeout.
Byte caps are not exact model token counts.

The verifier first reproduces all four missing-interface failures under the new
dependency image. The agent then searches the repository using ordinary tools.
Final acceptance requires runtime success, four passing cases with exact package
versions and a nonempty diff limited to existing Python files under `httpx/`.
This extra source-scope check is post-run; host workspace policy enforces the
existing protected-path and declared-work-item restrictions during execution.
Do not describe this as an OS-level whole-agent sandbox. The agent remains on
the host; only verifier commands execute in Docker.

`execution-started.json` is exclusively created before baseline execution.
Completion, interruption and environment failure all consume this prepared
attempt. Do not delete the marker to retry or count another output directory as
an untouched first attempt. This is a local guard, not a global attempt registry
or proof of human/model non-exposure. Local hashes are not signed provenance.

`results.json`, `baseline.json` and `run/` preserve outcome and runtime evidence.
Errors remain visible, and failed runs are not silently retried. Preparation is
not operator-unseen preregistration; no cohort denominator or benchmark readiness
is claimed. The other selected cohort members remain deferred.

Three runner tests cover acceptance identity, source/manifest drift and exclusive
attempt claims. A live model trial has not yet been performed.

## First preparation environment failure and path correction

`httpx-1588-first` stopped before inference: Docker returned
`ModuleNotFoundError: No module named 'httpx'` with empty stdout. This is not the
expected HTTPcore API failure and was correctly rejected. The source was present
on the host. The baseline caller passed a relative workspace path through to a
Docker bind source; the original reproduction used an absolute path.

`CommandRunner.run` now resolves existing workspace/report directories before
constructing the mount and subprocess cwd. A regression test checks both bind
sources and cwd from relative inputs. Acceptance, model, task and budget are
unchanged. The original failure and execution marker remain intact.

A new preparation records the corrected implementation separately:
`.keel/transition-trials/httpx-1588-path-fix`. It is an environment-fix rerun,
not an additional independent task or an erased first attempt. Execute with:

```powershell
python examples/run_transition_task.py --output .keel/transition-trials/httpx-1588-path-fix --execute
```

The host-side path regression and audit tests pass. Corrected live Docker
execution still requires user-side verification; no model success is claimed.

## Agent result after the path correction

`httpx-1588-path-fix` reproduced the baseline and entered model execution.
It completed unsuccessfully: 23 model calls, 50,894 tokens, 169.391 runtime
seconds, no changed files; Implementer exhausted its 12 turns. This remains a
failed trial, not an environment exclusion or a success after retry.

The Implementer ledger records list/search/read actions only, no replacement.
It found `httpx/_transports/default.py`, but four of its twelve actions requested
more than the inclusive 80-line bound and were rejected. Later reads overlapped
earlier windows and old conversation turns were archived. This supports a tool
usage/pagination bottleneck; it does not prove that pagination alone caused the
failure or that the model could produce a correct migration patch.

The generic gateway now offers `read_page(path, start_line)`, sharing the same
80-line/3,000-character implementation, role visibility, source hashes and tool
budget as `read_lines`. The host determines the page end and returns `next_line`.
Existing `read_lines` validation remains strict. The role prompt prefers host
pagination; it adds no repository-specific location or migration hint. One test
walks a multi-page source without gaps, checks caps, charging and invalid inputs.
Gateway tests (8) and agent tests (22) pass. No subsequent live model gain is
claimed. Any follow-up is a development rerun of an already observed task.

## Pagination trial and exact Scout envelope compatibility

`httpx-1588-pagination` completed unsuccessfully in Scout: 12 model calls,
28,693 tokens, 79.296 seconds, no source changes. Nine responses returned a
bare `summary`/`files` object instead of the required `final` envelope. The
trial did not use `read_page`, so it provides no pagination-effectiveness result.
The existing execution marker correctly refuses a second invocation.

The shared AgentSession now recognizes exactly that Scout output shape only
after a successful evidence-producing tool action in the same session. It
requires exactly two keys, a string summary and an array of string paths. It
adds only the outer `final` wrapper; it does not invent fields, locate files,
accept extra keys, bypass path validation or modify Implementer/Planner output.
Even when `require_evidence` is disabled, normalization still requires an actual
local observation. Wrapped output continues through existing Scout path checks,
planning, edit policy, verifier and audit. Raw model output remains in the ledger;
`action_envelope_normalized` records rule `scout-final-wrapper-v1` and its fact ID.

Offline shape replay recognizes the nine saved objects, without replaying the
model or claiming a task pass. Added tests cover successful end-to-end editing
without a paid formatting retry, plus wrong roles, no evidence, extra/missing
fields and invalid types. The existing early bare-output rejection test remains
passing. Agent tests (24) and native/LangGraph orchestration tests (13) pass.

Prepared follow-up: `.keel/transition-trials/httpx-1588-envelope-fix`. This is
another development rerun with the same task and budget, not independent data:

```powershell
python examples/run_transition_task.py --output .keel/transition-trials/httpx-1588-envelope-fix --execute
```

## Planner cap feedback

The envelope-fix trial passed Scout and failed in Planner after 6 total model
calls, 10,937 tokens and 43.625 seconds, with no changes. Planner returned a
correctly wrapped two-item array (inspect, then implement) despite the configured
one-item cap. This is a distinct contract failure, not a Scout envelope failure.

Planner count/type checks now also run inside the session feedback loop, before
returning a final plan. The prompt explicitly states the configured cap and asks
for inspection to be folded into implementation work. Invalid counts receive
correction feedback; retries consume existing role/global budgets. The outer
plan validation remains in place. No extra work items are accepted and no plan
is silently merged by the host. The exhausted-cap regression still checks no
edits or verification; a new test covers a corrected plan in the same session.

The next development preparation is `httpx-1588-planner-feedback`. It retains
the same task, model settings and budgets. No live improvement is yet measured.

## Optional hierarchical proposal diagnostic

After offline capacity checks, the runner accepts preparation-only
`--strategy localized-proposal`; the default remains `agent`. Execution uses
the strategy frozen in prepared.json and rejects a runtime override. This is
a staged localization/patch pipeline diagnostic, not the equal-access
single-session comparison described in agent-comparison-plan.md.

Prepare a new directory (already prepared locally as `httpx-1588-localized-v1`):

```powershell
python examples/run_transition_task.py --package .keel/task-packages/httpx-1588-v1 --model-config .keel/model-openai.json --strategy localized-proposal --output .keel/transition-trials/httpx-1588-localized-v1
```

Execute once:

```powershell
python examples/run_transition_task.py --output .keel/transition-trials/httpx-1588-localized-v1 --execute
```

Base source, goal, model configuration, verifier/image, audit and global budgets
are unchanged. Normal staged execution has three model requests (file selection,
exact definition selection, patch); malformed selections or source/cap failures
terminate without a hidden model retry. Multi-selection context can still
overflow. No reference patch or curator file location is provided.

Final results include strategy and explicit checks for runtime success, nonempty
source-scoped diff, acceptance and model calls. Old artifacts stay untouched.
Freeze checks and exclusive execution markers still apply. A pass would support
this one development task only, not orchestration superiority or benchmark
readiness. A failure remains recorded; do not immediately tune and rerun.

Four runner tests, six localized-proposal integration tests and two exact-source
tests pass. No live outcome for this new preparation is claimed.

## Planner-feedback trial: persistent read friction

That trial failed in Implementer without changes: 19 model calls, 41,706 tokens,
123.688 runtime seconds. Its twelve actions were two directory listings, five
searches and five read requests. Three read requests asked for 220/240 lines and
were rejected. The last two read requests finally read the first source pages.
It never called `replace` or `read_page`. Adding an alternative tool and a prompt
preference did not resolve the observed behavior.

The existing `read_lines` contract now treats its end as a requested end, rather
than rejecting an oversized range. The response is still bounded to at most 80
lines and 3,000 characters, and includes actual end, requested end, `truncated`,
source hash and `next_line`. Character truncation remains line-aligned. Invalid
types, nonpositive/reversed ranges, out-of-file starts and path escapes remain
errors. A page is partial evidence, not proof that all requested lines were read.
This deliberately changes the prior strict range-validation contract; its test
now checks explicit bounded partial results, charging and actual continuation.
No file-specific repair hint, extra budget or write permission is introduced.

Gateway tests (8) and Agent tests (26) pass. A scripted-model integration test
exercises oversized reading, explicit continuation to a late source line, exact
replacement and real local verifier success. It checks runtime behavior, not
whether a live model will choose those actions. No live model success follows
from these checks. Pause repeated paid runs of this task; retain all failures.
