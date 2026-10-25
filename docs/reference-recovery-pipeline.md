# Reference recovery across stages

`keel.reference_pipeline` connects registered recovery operations without asking a
model to rewrite environment scripts or weakening reference acceptance.

The controller operates on a failed **reference** grade for one frozen task. It
validates the reference export, task inputs and official result receipt when one
exists. Its transition rules are:

| Observation | Authorized next operation |
|---|---|
| Cold build completed before overall timeout | Check retained image against archived build ID, then grade once using the cache |
| Graded reference failed | Existing evidence-gated SCM/dependency recovery |
| Adapted build failed with supported transient APT evidence | Registered `retry_acquire`, preserving previous policies |
| Fresh reference accepted | Return its exact directory to the original repair task |
| Signature failure, invalid evidence, unsupported failure or depleted time | Preserve result and stop; never replace the task |

Each strategy executes at most once. One deadline spans all recovery stages;
completed preparation never becomes proof of acceptance. A required checkpoint is
written before dispatch, then result/evidence hashes are committed before routing
the next observation. `--resume` verifies completed artifacts and returns recorded
results without dispatch; it refuses an interrupted unreceipted stage. New budget
or implementation migrations require a new explicit output, preserving old costs.

Use `examples/recover_reference_pipeline.py` for an existing failure. An explicit
`--recipe-grade` supplies the original same-task build provenance when the current
grade reused an image. The controller does not search arbitrary historical logs.

In **newly prepared** `run_swebench_batch.py` plans, enabling both
`--recover-network --recover-compatibility` selects this chain. Initial reference
grading and recovery share the configured reference time allowance. Only an
accepted reference advances to Agent execution. A valid recipe-scoped retained
reference cache is explicitly passed to that task; test containers/results remain
fresh. Single-recovery modes preserve their existing behavior. This rollout uses
fixed zero-model recovery operations, not a general model-driven supervisor.

The historical replay in `.keel/repair-review/reference-pipeline-replay-v1` uses
actual archived failure/grade fixtures with intercepted executors. It proves
routing/provenance behavior, not a new Docker run or autonomous live acceptance.

## Diagnostic archive transport

`keel.apt_archive_bridge` provides an opt-in bridge between diagnostic BuildKit
cache mounts and the official harness's Docker SDK build backend:

1. Require a completed diagnosis bound to the exact setup script and immutable
   official environment image. Read that existing cache without network or APT.
2. Export `.deb` files plus size/hash manifest into a data-only local image. If
   the cache was pruned, report unavailable; do not redownload to manufacture a
   cache hit. Limits bound archive count/bytes and hashing streams file contents.
3. Bind archive image ID, original base image ID and exact APT command identity.
   Reject mismatched recipes and unrecognized artifact fields.
4. A restricted harness adapter checks those image identities and injects a copy
   from the local archive image into the instance Dockerfile. Before the original
   APT chain it validates/copies the files. An exit trap restores the original
   Docker cleanup hook and removes supplied cache entries even on APT failure.
5. Keep source, tests, APT command/package selection, repository signatures and
   warning policy unchanged. Actual APT reuse still depends on current package
   selection; injected bytes are not themselves a download-savings measurement.

The cache adapter is installed before recipe-cache hashing. Artifact identity
therefore contributes to the instance key. Reference receipts and the verifier
forward its hash-bound policy; a cached score is never used as a new test result.

`export_apt_archives.py` exports a completed cache. `grade --apt-archives
artifact.json` uses it explicitly. Diagnostic network recovery supports
`--bridge-archives`: export after the workload completes, reserve fresh grading
time, and stop if requested bridging is unavailable. Batch preparation exposes
this in diagnostic network-only mode; the combined recovery chain avoids running
a redundant diagnostic APT workload in the first place.

`check_apt_archive_bridge.py` is a zero-model **live Docker transport check**. It
reads an existing cache and imports it through the real official SDK builder,
with network disabled and no package installation. Its success proves transport
and cleanup, not official task acceptance, install correctness or measured cost
savings. Exported artifact images are retained for explicit reuse; only its owned
temporary consumer image is removed. Docker daemon cleanup is not certified by
the local watchdog.

Prepared live check: `.keel/repair-review/apt-archive-bridge-live-v1/run.ps1`,
600-second shared selfcheck deadline plus 60-second process-containment allowance.
It requires no model credential. The cache may have been pruned since the earlier
diagnosis; that is a genuine unavailable preparation result, not a repair score.

These changes implement infrastructure behavior and structured evidence. They do
not automatically promote operational advice cards, train model weights, turn
documentation into runtime memory, or establish held-out generalization.

## Current validation record

98related regressions pass in7.869s. Actual archived24026failure/policy/grade replay follows compatibility then APT retry without model/Docker calls; acceptance in that replay is a historical fixture. Two full-suite profiles were attempted and preserved: harness Python ran1112tests/223.815s with5errors due missing tree_sitter; development Python ran1112tests/247.724s with1failure+1error in real MCP subprocess tests, both reporting Windows access denied. Do not claim the full suite green in this tool environment. New archive unit tests no longer require an installed official harness; the local focused suite includes final source.

Combined user-terminal validation launcher: `.keel/repair-review/reference-automation-live-v1/run.ps1`. It runs those two real MCP checks under a90s watchdog and, if passed, the frozen600s Docker archive selfcheck. No model key/calls, no APT installation/redownload, no fresh official grade. Existing successful SDK check can be reused with frozen-source validation; failed/interrupted checks are preserved. Actual Docker backend import and pipeline live recovery remain unverified until their corresponding real runs complete. No operational card auto-promotion, weight training or independent-transfer claim.


### Dockerfile and shell parsing are separate boundaries (2026-10-25)
Actual apt-archive-bridge-live-v1 failed before cache access: Dockerfile line3 unknown instruction import. Shell quoting a multiline Python program does not continue a Dockerfile RUN instruction. Write the program as an LF context file, COPY it and use a single-line RUN. tests.test_apt_archive_bridge now inspects the actual generated build context at the build boundary, checks instruction framing, copied program compilation and offline flags.27 focused checks pass; this is not live Docker validation. Preserve v1; v2 reuses original diagnosis/cache and completed actual MCP checks without APT/model fallback.


### 2026-10-25: live cross-backend APT archive transport verified
User ran apt-archive-bridge-live-v2: watchdog passed200.047s, actual selfcheck189.171s, export38.641s, zero model calls. Official SDK consumer observed389archives/439051774bytes (about419MiB). Artifact JSON SHA256 matches export receipt; no consumer_cleanup_error reported. This supersedes pending Docker transport status only: existing BuildKit cache -> data-only image -> official SDK build now verified with network disabled and no APT install. Does not establish actual APT reuse/download savings, fresh official acceptance, automatic pipeline live success, or daemon-wide cleanup. Next validation should reuse retained hash-bound artifact in real original-workload reference grading, preserving environment policies and prior scores, rather than rerun the transport smoke or model repair.


### 2026-10-25: prepared real archive-consuming reference validation
Prepared apt-archive-reference-live-v1 from current frozen runtime, same24026task/reference export and accepted dependency/plugin/retry_acquire policies. Reuses hash-bound389archive artifact, not diagnostic rerun. New recipe cache scope forces archive adapter into instance preparation;1800s grading plus60s containment, zero model calls. Checks retained base/archive IDs and all task/export/policy/artifact inputs before dispatch. Network remains available to unchanged APT for metadata/missing packages; build log must establish actual reuse/download amount. Fresh reference acceptance pending; historical pass not replaced.


### 2026-10-25: actual APT cache reuse and fresh reference acceptance
apt-archive-reference-live-v1 watchdog passed1020.125s, zero model calls. Fresh grading.json official_resolved=true, runtime_status=reference_only, no infra failure. New instance build imported389archives/439051774bytes. Actual APT log reports Need to get0B/5003kB and0B/434MB: archive reuse now observed during real install, superseding transport-only uncertainty. Metadata update still fetched49.0MB; do not claim network-free construction or total network savings. Official report hash checked against new run report. Original task/reference and compatibility/plugin/retry_acquire policies preserved, declared reconstructed conditions; this is environment/reference validation, not a new autonomous repair score or proof of full automatic recovery chain. Next gap: real end-to-end registered recovery handoff, preserving the successful preparation rather than repeating downloads.


### 2026-10-25: connect retained archive evidence to registered recovery controller
Developer added optional apt_archives and explicit instance_cache_scope to reference_pipeline/CLI. Hash-bound artifacts participate in input/resume identity; APT retry checks original base tag and exact command before forwarding; conflicting existing archive policy rejected. Scope reuse affects recipe builds only, fresh official tests still required.38related checks passed4.811s; initial new regression fixture incorrectly parsed FROM platform flag, corrected test fixture (not product workaround). New reference-pipeline-live-v1 starts from archived24026APTfailure, uses just-accepted artifact/cache scope with pre-dispatch image identity guard,600s shared/660s watchdog, zero model calls. Live outcome pending; proves only registered APT route and fresh reference acceptance if successful, not compatibility selection or Agent repair handoff. No business-task hardcoding or prior-score replacement.


### 2026-10-25: live registered APT recovery route verified
reference-pipeline-live-v1 completed178.766s (watchdog180.031s), status reference_verified, zero model calls. Exactly one completed apt_retry stage from archived original APT failure; original task/policies retained and archive artifact forwarded. Actual harness says Found1existing instance images. Will reuse them; Running1unevaluated instances; resolved1. Fresh per-run official report and all controller artifact hashes verified. This is real controller routing/build reuse/fresh test execution, not a mocked replay or cached score. It does not newly test cold compatibility discovery, automatic archive discovery/export, or subsequent Agent repair dispatch; artifact and cache scope were explicitly supplied by developer launcher. Next work should close those remaining orchestration gaps or assess another independent failure, rather than repeat the accepted reference build.


### 2026-10-25: bounded preparation discovery replaces exact artifact handoff
Added reference_assets.discover_assets and reference_pipeline/CLI preparation_roots. Explicit evidence roots/direct children only,30s shared-deadline slice and256directory envelope; validate same frozen task, official report hash/resolved flag, identical registered policies, APT command/base, archive/base/retained instance image identities. Reject mismatches with reasons; no matching asset stops before grader instead of blind rebuild/download. Selected evidence hashes enter required pipeline artifact ledger and resume validation. Fresh grading remains required; prior acceptance never becomes current score.65focused tests pass8.159s incl5discovery variants and existing batch original-task handoff. Initial implementation accidentally inserted discovery into cold-timeout branch; new tests caught all5cases, moved to APT route before freeze. Prepared reference-discovery-live-v1: authorized evidence directory only, no exact archive/scope passed,600s/660s,0models; real outcome pending. Existing batch Agent handoff already tested, not newly live-verified here. Discovery is opt-in CLI, not global automatic memory search or new task repair claim.


### 2026-10-25: live preparation discovery and fresh reference acceptance verified
reference-discovery-live-v1 completed179.203s (watchdog180.062s), status reference_verified,0modelcalls. Controller independently selected matching apt-archive-reference-live-v1/results from supplied evidence root, resolved archive path/cache scope and inspected retained instance image ID. One registered apt_retry stage; harness explicitly reused existing image and ran1unevaluated instance. Fresh official report confirms2FAIL_TO_PASS+764PASS_TO_PASS, no failures; all selected/output evidence hashes verified. This validates bounded discovery plus recovery routing and fresh scoring on exposed24026, not broad knowledge retrieval, cold recovery discovery or new Agent repair. Scope remains explicit evidence roots/direct children. Existing batch recovery->Agent path remains unit-tested rather than newly live-tested by this experiment; next integration should expose discovery configuration there, rather than repeatedly rescore the same reference.


### 2026-10-25: preparation discovery integrated into batch recovery and original-task handoff
run_swebench_batch preparation now accepts repeatable preparation-root only with combined network+compatibility recovery, validates roots before output creation, freezes authorized paths in plan hash, forwards them to real controller. Execute cannot override frozen roots. Existing accepted-reference path forwards exact recovered directory and reuse_reference_image to original Agent; unsuccessful discovery/recovery does not start that task Agent and preserves fixed batch IDs. Added positive/negative wiring tests with mocked controller/Agent;65previous+2new=67focused checks pass9.776s, zero provider/Docker. Discovery execution itself had prior real evidence, but this batch integration is not a new live model success. No new paid run prepared merely to repeat accepted reference scoring. Next meaningful evaluation is a bounded complete task run or independent failure case, with preparation reuse and model costs reported separately.


### 2026-10-25: bounded real recovery-to-Agent experiment prepared
Added prepare_continuation API to existing batch runner:one explicit exposed frozen task, archived unresolved reference inputs hash-bound, no initial grading replay or inherited candidate source. Existing controller automatically discovers prepared assets, freshly validates environment, then launches original task from base. New strict require-all-resolved exit checks both official acceptance and passed runtime; prevents a completed unresolved batch appearing as watchdog pass. Frozen recovery-agent-e2e-v1 uses sameGPT5.4configuration/localtokenizer,20calls180000tokens80tools,600sreference plus1200ssharedtrial incl300sfinalreserve and60scontainment. New outputs/budgets, full transcript, no paid calls dispatched bydeveloper.69related checks passed9.279s, incl original-task handoff, no duplicate initialgrade, changed oldevidence rejection and strict exit statuses. Live outcome pending; exposed developmental orchestration check, not new held-out score or evidence of general RSI.


### 2026-10-25: real recovery -> original Agent -> final official acceptance passed
User recovery-agent-e2e-v1 watchdog passed740.078s. Real batch pipeline discovered existing matching preparation, took188.203s to verify reference and handed its exact directory/cache scope to fresh-base GPT5.4 Agent. Trial continuation=null (no inherited candidate), runtime passed, official_resolved=true,1verification round,4modelcalls24682tokens16tools306.063sAgent,542.203strial including final grade. Prediction1523UTF8bytes; full model transcript95573bytes retained. Both new reference and final reports independently confirm2target+764preservation successes; report hashes and all pipeline artifacts verified. Original failed reference and earlier costs remain; reconstructed policies/cache reuse explicit. This is a live exposed-development integration success with preexisting human/developer-prepared assets, not cold-start autonomous environment discovery, independent task generalization, weight training or RSI. Compared old manual trial4calls26887tokens18tools, new trial24682tokens16tools; one unpaired same-task observation cannot establish causal efficiency gains. Next priority is freeze this working version/check CI, then one new independent complete task or counterexample; do not keep retesting only24026.
