# Repair from a verified environment

`examples/run_factory_task.py` consumes any generic `task_factory` output directory containing `factory.json`, `base/` and `gold/`. It does not search GitHub or rebuild images.

Before invoking a model it validates frozen acceptance, verifies installed versions, and reruns base/old, base/new and gold/new. The existing three-cell gate must still pass. It copies only base into a separate solver workspace and uses the campaign's adaptive recovery configuration: Critic can request repair, replan or stop within fixed budgets. Tests and verification remain protected. Full runtime artifacts are under `solver-run/`; `trial.json` records the outcome and trajectory.

Example in PowerShell:

```powershell
python examples/run_factory_task.py --factory .keel/python-transition-smoke/v1/factory --output .keel/factory-trials/python-smoke-v1 --model-config .keel/model-openai.json --execute
```

Without `--execute`, it checks the artifact and prints a plan without model calls or Docker execution. Execution uses metered model calls. Output must be new and outside the factory directory. No discovery or environment-building cost is repeated, but environment revalidation consumes time.

The smoke fixture remains synthetic even when repaired by a model. It is a pipeline control, not an independent repository benchmark, full TLS evaluation, or evidence of recovery improvement. A first-pass success does not demonstrate recovery. Artifacts are local trusted inputs, not cryptographically authenticated third-party submissions.

Validation: three unit tests cover altered acceptance rejection, preflight failure before solver invocation, and the base-only adaptive solver boundary. Live Docker/model execution is separate from these tests.

## Frozen repeated comparison

Prepare with `examples/compare_factory_recovery.py --factory FACTORY_DIR --model-config MODEL_FILE --output NEW_COMPARISON_DIR --repeats 3`, then execute with `python examples/compare_factory_recovery.py --output NEW_COMPARISON_DIR --execute`. Repeat `--factory` to include more verified tasks. Preparation makes no model or Docker calls. Execution uses the model API.

The comparison freezes full base/gold inventories, factory receipts, model configuration hash, implementation file set and hashes, and randomized run order. Each task gets recovery off (0) and on (3 verification repair opportunities), repeated three times by default. Both arms use the same global per-run limits and separate fresh base workspaces. The off arm disables the full recovery controller, including correction before verification; this is not an isolated measurement of verification retries. Environment revalidation is repeated per run, so remaining solver wall time may vary slightly.

With three repetitions there are six metered runs per task; each has at most 30 model calls and a 900-second budget including preflight. Results retain errors, report incomplete coverage explicitly, and distinguish repetition count from unique task count. Recorded solver cost excludes environment-preflight work. `completed` describes experiment completion, not universal success. No significance, causal effect or held-out status is inferred. A synthetic fixture remains synthetic.

Implementation/input drift stops execution; trial failures retain their rows and do not skip the other planned runs. Execution is exclusive and does not overwrite or resume a prior invocation. Do not alter the runtime between preparation and execution.
