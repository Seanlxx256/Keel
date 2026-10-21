# Keel execution with official SWE-bench feedback

`examples/run_swebench_task.py` connects frozen issue/base source to adaptive Keel execution, per-round official verification, prediction export, and a separate final official grading run.

Prerequisites: frozen task artifacts, a successful matching reference-only preflight using harness 3.0.0, a model configuration with credential environment references, Docker access and the dedicated harness interpreter. The runner checks task data against the preflight and checks the selected interpreter's harness version before inference. Default invocation without `--execute` performs input checks and prints a plan without model calls, Docker execution or cloning.

```powershell
python examples/run_swebench_task.py --task .keel/swebench/first-official-preflight-v1/task --reference-grade .keel/swebench/first-official-preflight-v1/reference-grade-v5 --model-config .keel/model-openai.json --harness-python .keel/harness-v3/Scripts/python.exe --output .keel/swebench/keel-trial-v1 --execute
```

The runner fetches an exact base snapshot into a separate repo. The model goal is only the issue; no reference source patch or test patch is copied into its workspace. Every verification produces the current git diff against the bound base HEAD and submits it to the official grader under a fresh run ID. It returns test identities/results and bounded observed test output, excluding setup/test-patch application text. Empty patches fail before launching a grader. No task-specific source location or solution is supplied by the adapter.

The existing adaptive runtime decides whether to repair, replan or stop. Limits: 30 model calls, 180000 tokens, 80 runtime tools, 1800 runtime seconds, six recovery actions and up to three verification repairs (four verification rounds). One verifier launch has a 600-second harness timeout. Preparation (including git fetch) and the separate final grading run are outside runtime accounting. Final grading is attempted even for runtime-failed partial/empty patches, with both verdicts retained. This first public task has unverified prior exposure and is exploratory, not an independent score.

The verifier **launcher runs on the host** under Keel's local command backend and invokes official Docker evaluation. It does not use Keel's restricted Docker CommandRunner flags. The official harness owns test execution, test patch application and cleanup. There is no claim that all Agent/MCP/host processes are containerized. Host subprocess interruption may not cancel every Docker-side build; inspect Docker state after forced termination.

Full outputs: `run/`, `verifications/`, `prediction/`, `final-grade/`, `trial.json`, `input-receipt.json`. The implementation and task receipts are checked before/after model calls; edit-free execution is required. Runtime report status and official resolved status remain distinct.

Optional `--recovery-progress` enables experimental per-round evidence inventory
and feedback to the next Critic, independently of diagnostic inspection. It is off
by default and recorded in plan/trial reports. It adds context but no model calls,
permissions or budget. See [recovery progress](recovery-progress.md) for verification
comparison rules and limits; it does not certify execution of a semantic next_check.

Validation: five task-runner tests cover configuration boundary, reference-preflight rejection, no-patch rejection, stripping setup/reference-test-patch text from feedback, and real git diff/HEAD binding. Bridge tests independently cover actual loader/transport contracts and mocked grading. No live Keel inference or repair success is claimed until the operator executes this runner.
