# Bounded indexing and validation resume

For the later `run-v3` continuation, use:

```powershell
python examples/run_frozen_retrieval_validation.py --plan .keel/retrieval-validation/run-v3/resume-plan/plan.json --resume-from .keel/retrieval-validation/run-v3 --output .keel/retrieval-validation/run-v4 --index-timeout 1800 --execute
```

This continues from the latest effective plan, preserving three baselines, five
successful external retrieval results and eight completed reranker jobs (541
previously scored pairs), subject to normal identity checks. New Django and
Astropy/CocoIndex work is pending. Failed Xarray input remains excluded.

## Follow-up Windows and Git-entry repairs

`run-v3` failed Django while publishing progress JSON with a Windows sharing
violation. `compass.progress.atomic_json` now retries replacement with bounded
backoff and unique temporary files. Index telemetry writes are throttled to
one per second within a stage; a persistent telemetry sharing violation logs a
warning rather than aborting indexing. Final result/checkpoint writes remain
mandatory. Validation status uses the same retried atomic writer. No elevated
permissions or global antivirus/permission changes are requested.

A real Windows test opens JSON without delete sharing, releases the handle during
retry and verifies complete publication. Persistent failures are bounded and
leave the previous JSON intact. This tests sharing semantics, not proof of which
reader/antivirus process caused the original error.

Astropy's failed CocoIndex copy was an uninitialized Git submodule, not an absent
Python dependency. Copies now inspect Git index modes: regular files are copied;
uninitialized gitlinks and declared symlinks are omitted with path/object/reason
receipts. Initialized submodules still fail pending explicit corpus policy, and
links are never dereferenced. This is generic Git-entry handling, not a pathname
exception. Real Astropy copy validation saved
`.keel/tool-checks/astropy-gitlink-copy-v2/result.json`: 1824 copied files, two
recorded omissions (`CITATION` symlink, `astropy_helpers` empty gitlink).

The derived plan explicitly authorizes reuse of formerly successful regular-file
CocoIndex results across this copy-only repair. Actual Requests and Pytest Git
indexes contain no symlink/gitlink entries, so their successful corpora are
unchanged. Ranking, embedding and snippet policy are not changed. Existing
embedding weight caches are also reused rather than downloaded into every new
run directory. Reranker code/weights are unchanged, enabling prior job reuse.

Resume precheck `.keel/retrieval-validation/resume-check-v5/resume-check.json`
verified the three baseline reuses and unchanged failure handling. The full
continuation has not been executed during repair. 69 related tests passed,
including real Windows sharing, Git-entry handling, checkpoint and cache tests.

The interrupted `.keel/retrieval-validation/run-v2` is preserved. Requests,
Pytest and Astropy baselines reproduce under source/dataset/index/range/packing
checks. Xarray failed input validation (`Invalid SWE line interval`). Django was
still indexing. No retrieval-quality defaults are promoted.

## Continue this run

```powershell
python examples/run_frozen_retrieval_validation.py --plan .keel/retrieval-validation/plan-v1/plan.json --resume-from .keel/retrieval-validation/run-v2 --output .keel/retrieval-validation/run-v3 --index-timeout 1800 --execute
```

The output must be new. A derived `resume-plan/plan.json` retains the tasks,
data hashes and ranking policy, recording original plan/run receipts and explicit
infrastructure implementation changes. The old frozen plan is not modified.
Changes outside the reviewed index/resume/worker files reject execution.

Three completed baselines are reused. The unchanged Xarray failure is retained;
no reference labels or substitute tasks are introduced. Django continues, then
external retrieval and ranking stages that had not started run. Final status
remains `incomplete` if Xarray remains excluded: four scored tasks are not five.

To check without starting indexing/inference:

```powershell
python examples/run_frozen_retrieval_validation.py --plan .keel/retrieval-validation/plan-v1/plan.json --resume-from .keel/retrieval-validation/run-v2 --output .keel/retrieval-validation/resume-check-v3 --check-resume
```

Actual checked artifact: `.keel/retrieval-validation/resume-check-v2/resume-check.json`.
Exactly three reusable baselines, one retained data failure and one unfinished
baseline were verified, without embedding or retrieval calls.

## Runtime fixes

- Index embedding uses a sliding five-minute model lifetime, avoiding reloads
  every batch. This changes the isolated validation builder, not all callers.
- `index-progress.json` records parsing/linking/embedding/publication progress.
  The parent prints stage, vector/file counts and elapsed time every ten seconds.
  Child errors are retained in `index.log`.
- Index subprocess deadline defaults to 1800 seconds, with a fifteen-second
  parent shutdown margin. Request timeouts shrink with remaining build budget.
- Each successful embedding batch commits a separate SQLite checkpoint. Identity
  includes embedding configuration, actual Ollama model digest and exact
  dependency-enriched text hash. Cached vectors are validated before reuse.
- Retrying rebuilds parsing/linking, reuses saved vectors, and publishes only
  after source fingerprint checks. Incomplete indexes are never published.

Old Django vectors were held in memory until final persistence and cannot be
recovered after termination. Django must rebuild once with this fix. Subsequent
completed batches are reusable. Old incomplete generations are retained. Parsing
and in-flight HTTP requests are not checkpointed.

## Stage reuse

Completed Compass results require matching data/source/configuration and exact
metric reproduction. A passed sweep is detected even if the outer status had not
yet changed to `baseline_ready`. Multi-hop resumes retain the original directory.

Completed external task/engine results require matching query/dataset/index,
packing, worker implementation and reproduced metrics. Successful engines launch
no new tool request; failed engines are retried. Completed reranker jobs require
matching model/revision/worker and identical query/code input. Only pending jobs
load the model and run inference. New and reused pair counts are separate;
all-cached runs import no model. Fusion replay may recompute deterministic metrics.

For another interruption, use the latest run directory as `--resume-from` and
its recorded `effective_plan` as `--plan`, with a fresh output directory.
Reuse is conditional on verified artifacts, never status alone.

## Verification

Tests cover interrupted batch reuse (32 saved vectors reused, only 8 remaining
computed), model identity isolation, publication/time limits, no-tool-call
external reuse, cached inference bypass and bounded child termination.
A real one-symbol tree-sitter/Ollama build completed:
`.keel/index-resume-smoke/progress-v1.json`; Ollama reported the model resident
afterward, verifying lifetime behavior. The full Django build and remainder of
the batch were not rerun during this repair; no large-repository speed claim.
