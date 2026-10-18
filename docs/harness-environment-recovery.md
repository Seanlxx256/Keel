# Bounded harness packaging recovery

This recovery path diagnoses unknown packaging failures from observed build logs and
metadata at the frozen BASE commit. The model selects a data-only recipe; it cannot
write shell commands, tests, source patches, or project-dependency overrides.
Allowed exact pins: pip, setuptools, wheel, flit_core, hatchling, poetry_core. The other
control is whether to disable build isolation. This is a supported action space, not
a promise to repair arbitrary OS, network, service or compiler failures.

The controller runs at most nine ReAct decisions and three builds by default, with a shared 2400-second,
120000-token and 20-high-level-operation allowance. Snapshot internals and harness
internals are not individually counted as tool calls. Each reference revalidation has
at most 900 seconds, bounded by remaining wall time. External Docker work may outlive
a terminated launcher; process timeout is not proof that Docker work was cancelled.

Every attempt preserves its response, recipe, logs and result. Reordered pins or changed
explanations do not create a new recipe. Invalid/repeated recipes consume an attempt
without rebuilding. Actual reference test failure requires a successful fixed diagnostic
inspection and citation of its evidence ID before another environment change; success
requires a real fresh official reference report. Partial progress never counts as pass.

Overlays are applied in an isolated harness process, leaving the installed package
unchanged. Environment hashes and instance image tags change. Only install commands
receive packaging setup; original test commands and result labels are preserved.
Successful overlay hashes propagate into every Agent verification and final grading.
Results are labelled reconstructed conditions, not unchanged official environments.

Existing failed preflight follow-up (model calls and Docker builds occur only with execute):

```powershell
python examples/recover_swebench_environment.py --task .keel/swebench/new-task-batch-v2/task-1/task --reference .keel/swebench/new-task-batch-v2/task-1/reference --failed-grade .keel/swebench/new-task-batch-v2/task-1/reference-grade --output .keel/swebench/pylint-7277-environment-recovery-v1 --model-config .keel/model-openai.json --harness-python .keel/harness-v3/Scripts/python.exe --execute
```

For new batches, add `--recover-environment` during preparation. Its action allowance
is frozen in the plan, separately reported from the 30 repair-model calls per task.
Execution still uses only `--output ... --execute`. Existing frozen batches are not
silently upgraded. Original and reconstructed environment successes are counted separately.

Local tests validate the loop with controlled build outcomes, rejected actions, repeated
plans, recipe propagation, and real installed harness TestSpec/cache integration without
Docker. They do not establish that the Pylint environment has recovered. Real-model
and Docker validation must be reported separately.

## ReAct observations after test execution

Reference reports and bounded test-failure excerpts are now included, excluding setup
and test patch contents. `inspect` accepts only module/distribution identifiers. A fixed
program records Python and installed-package versions, import locations/errors,
distribution requirements and entry points in the most recent instance image. The
probe uses a network-disabled, read-only container, no host mounts or supplied credentials,
memory/PID limits and a bounded lifetime with cleanup. Package imports can execute code
inside this container; inspection is not a claim of zero side effects inside memory/tmp.

`rebuild` after a graded failure must cite an inspection ID from the current environment.
The host checks execution/provenance, not that the model's causal explanation is true.
Only packaging tools remain editable; unsupported causes require stop. Diagnosis has
bounded context and reports omitted log lengths. It does not grant arbitrary probes,
system installs or project-dependency changes. These remain explicit capability limits.

To continue investigating the already-built failed Pylint overlay, use its attempt-1
directory as `--failed-grade`, the same frozen task/reference, and a fresh output.
This starts a new budget and preserves the previous failed attempt; it is not a shared
budget continuation or a first-attempt benchmark result.

## Fault-injection acceptance

`tests/test_harness_environment.py` and `tests/test_environment_probe.py` exercise the
controller with scripted model responses and injected faults: missing image restoration,
probe timeout/cleanup, alternative inspection after timeout, failed evidence rejection,
premature non-environment conclusions, duplicate actions and decision-budget exhaustion.
These test host orchestration and provenance enforcement, not real-LLM reasoning quality.

Stop reports distinguish undetermined, unsupported scope and non-environment hypothesis.
The last requires successful current-environment inspection citations; it remains an
unverified model interpretation (`root_cause_verified=false`). A failed inspection cannot
authorize this conclusion. The host cannot determine semantic truth from free-form prose;
raw model responses remain archived and must not be presented as verified facts.

Run the no-model/no-Docker fault checks:

```powershell
python -m unittest discover -s tests -p test_harness_environment.py -v
python -m unittest discover -s tests -p test_environment_probe.py -v
```
