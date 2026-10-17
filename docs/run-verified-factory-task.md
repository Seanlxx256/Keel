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
