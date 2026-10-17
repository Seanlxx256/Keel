# SWE-bench artifact and grading bridge

## Live output

Grading now starts an unbuffered child (`-u`, `PYTHONUNBUFFERED=1`), tees stdout/stderr to both the console and `harness.log`, flushes log writes, and prints a liveness heartbeat every ten seconds. The heartbeat reports output bytes and the latest internal log path when available. It indicates the process is alive, not that tests are progressing. `grading.json` is written with running status before launch and updated on completion/error. Existing processes started by the previous bridge are unaffected. A real local child-process test verifies output forwarding, log preservation and a heartbeat during a quiet interval; nine bridge tests pass. This is not live Docker grading validation.

## Harness compatibility

### Windows line-ending failure in reference-grade-v4

The first completed official grading reported unresolved, but `test_output.txt` shows `pipefail` option errors, paths ending in literal `\r`, failed Conda activation and a failed test-patch application. The tests did not execute in the intended environment; this must not be interpreted as evidence against the reference repair. The original official report remains unchanged.

The bridge now invokes the unchanged official module through `swebench_harness_entry.py`. Only on Windows, a scoped transport wrapper sets LF-only `Path.write_text` output for `.sh`, `.diff` and `.patch` artifacts. It does not replace text, modify data records, tests, patch logic or grading. Other files and Linux execution retain their existing behavior. This is an explicit host transport adaptation, not official upstream functionality. Its implementation is part of the local evaluation code and must be held fixed for comparisons.

Twelve bridge tests cover writer restoration, unmodified supplied content and actual LF bytes on this Windows host. A local transport probe of the previous generated eval script verified CRLF removal with no other byte changes. Cached images can be reused by the official harness; a fresh grading output/run ID is still required to validate actual test execution. No successful reference score is claimed before that run.

The 3.0.0 live retry exposed another transport mismatch: its installed loader treats both `.json` and `.jsonl` as a whole JSON document and expects a list, so a one-line object failed with `TypeError: string indices must be integers`. Grading now materializes a separate `grader-input.json` array and records its hash without changing frozen source receipts. Direct invocation of the installed official 3.0.0 `load_swebench_dataset` loaded exactly `sympy__sympy-16450` successfully from this array on the real interpreter. This checks actual loader interoperability without Docker or model calls; image startup and grading remain unvalidated.

The first live reference preflight installed swebench 5.0.2 and failed before Docker tests with `KeyError: image`: its new task schema expects image/eval_script/log_parser/eval_type, absent from the frozen classic Verified export. The earlier unpinned installation instruction was incorrect for this record format.

Use `requirements/swebench-eval.txt` (swebench==3.0.0) in a dedicated virtual environment for this classic-data route. Version 3.0.0's official `make_test_spec` builds environment and test scripts from repo/version/base_commit/test_patch. The bridge now checks new-schema requirements before subprocess execution and supports both `logs/evaluation` and classic `logs/run_evaluation` report locations. Eight mocked interface tests pass; Docker grading with the pinned harness still requires live validation. The 5.0.2 failure remains an infrastructure/interface error, not a reference or agent score.

Version-specific sources: [3.0.0 task specification](https://github.com/SWE-bench/SWE-bench/blob/v3.0.0/swebench/harness/test_spec/test_spec.py), [3.0.0 log directory](https://github.com/SWE-bench/SWE-bench/blob/v3.0.0/swebench/harness/constants/constants.py).

`keel/swebench.py` and `examples/swebench_bridge.py` implement a local artifact boundary. They do not yet download tasks, prepare solver workspaces from official images, or run Keel inference. Existing Compass SWE retrieval scripts do not provide those missing repair-execution steps.

The bridge supports four actions:

1. `prepare --dataset LOCAL_JSON_OR_JSONL --instance-id ID --output TASK_DIR`: select exactly one full local dataset record, hash the dataset and extracted artifacts, write a whitelist-only `solver-task.json` and a separate private `grader-dataset.jsonl`. The latter contains reference and test patches and must stay outside the solver workspace.
2. `reference --task TASK_DIR --output REFERENCE_EXPORT`: export the reference patch solely for environment preflight. It is labelled `reference_only`, never an agent success.
3. `export --task TASK_DIR --run KEEL_RUN_DIR --output PREDICTION_EXPORT`: export `changes.patch` to official JSONL prediction format. The runtime goal must equal the frozen problem statement. Failed runs and empty patches remain exportable, with status preserved. Goal matching is not source-provenance verification.
4. `grade --task TASK_DIR --export EXPORT_DIR --output FRESH_GRADING_DIR --execute`: invoke the separately installed official `swebench.harness.run_evaluation` with the private local dataset, one instance and one worker. Without `--execute` it prints a plan. Each execution uses a fresh run ID and output directory to avoid harness cache reuse. Docker and dataset dependencies must already be available in that execution environment. This bridge does not install them.

Example environment preflight after obtaining and versioning a local official dataset export:

```powershell
python examples/swebench_bridge.py prepare --dataset DATASET.jsonl --instance-id INSTANCE_ID --output .keel/swebench/task-1
python examples/swebench_bridge.py reference --task .keel/swebench/task-1 --output .keel/swebench/reference-1
python examples/swebench_bridge.py grade --task .keel/swebench/task-1 --export .keel/swebench/reference-1 --output .keel/swebench/reference-grade-1 --execute
```

`grading.json` records `runtime_status` separately from `official_resolved`. Exit zero without an instance report is a grading error. Missing/invalid reports never imply success. The external report is trusted as a local harness artifact, not cryptographically authenticated. A resolved patch can coexist with a failed internal runtime verdict; both are preserved rather than silently reconciled.

Current validation: six unit tests exercise answer-field separation, export of failed runs, task drift/goal mismatch, reference labels, absence of report despite exit zero, and parsing a fresh per-instance report. These tests use mocked harness execution and do not establish Docker interoperability or a benchmark score. The complete real-task inference-to-grade loop remains unvalidated.

Primary contracts checked during implementation:

- [Official prediction format, evaluation command and result caching](https://www.swebench.com/SWE-bench/guides/evaluation/)
- [Official local JSON/JSONL dataset loading](https://github.com/SWE-bench/SWE-bench/blob/main/swebench/harness/utils.py)
- [Official per-instance grading fields](https://github.com/SWE-bench/SWE-bench/blob/main/swebench/harness/grading.py)

Downloaded dataset revisions, installed harness version and task exposure still need to be fixed before a real independent evaluation. Local file hashes alone do not prove unseen tasks or upstream authenticity.
