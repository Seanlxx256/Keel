# Fixed three-task exploratory batch

`examples/run_swebench_batch.py` prepares exactly three new task IDs across two repositories, then executes them serially using the existing task runner. It does not change Keel's repair strategy.

Preparation uses a fixed seed, ranks repository names and instance IDs by SHA-256, and interleaves tasks from the two selected repositories. Issue text, patches and outcomes do not influence ranking. Registered development repositories are excluded. IDs found in prior bounded local artifacts under docs/.keel are excluded as well. The artifact audit excludes raw dataset caches and source clones, skips files over 5 MB, and records omissions. This is an exposure check, not proof of human/model novelty or a representative sample. `heldout_tasks` remains zero.

The plan binds the dataset file hash, task/reference receipts, model configuration hash and full implementation file set/hashes. Model configuration contents are not copied into the plan. All later execution checks these bindings. Preparation must happen after code changes are complete. A new commit with identical file contents does not change file hashes; editing code/config after preparation invalidates execution.

Execution runs reference preflight, then Keel inference only if the reference passes. Failed references remain explicit rows and are not replaced with easier tasks. Failed repairs remain rows. Errors in one task do not suppress the other planned tasks. Input/implementation drift stops the batch before further paid calls. Exclusive execution prevents accidental duplicate submission; there is no automatic crash resume or overwrite.

The same task configuration applies to every task: 30 model calls, 180000 tokens, 80 runtime tools, 1800 runtime seconds, six recovery actions and up to four verification rounds. Three tasks permit at most 90 model calls. Reference preflights and separate final grading consume additional Docker time outside runtime accounting. Each reference/final harness run can take up to 1800 seconds. Do not interpret process completion as all tasks passing.

`results.json` starts with all three planned rows and is updated after each phase. It distinguishes reference failures, whether an agent ran, runtime outcome, official resolution and cost. The frozen task list remains unchanged regardless of results. When evaluating recovery efficacy, a later paired on/off study is still needed; one enabled-only batch cannot attribute improvements to recovery.

Prepare using `--dataset LOCAL_PARQUET_OR_JSON --model-config CONFIG --harness-python PYTHON --output NEW_BATCH_DIR`. Then execute using only `--output BATCH_DIR --execute`. Preparation performs no model/Docker calls; execution uses the configured paid model API and official Docker harness. Dataset and task artifacts include curator-only reference answers; do not mount the batch directory as a solver workspace.

Four unit tests verify seeded order-independent selection, exclusions, model-setting drift rejection, reference integrity, retaining failed preflights while continuing other tasks, and preventing accidental re-execution. Live batch results remain separate from these unit tests.
# Preparation discovery in the combined recovery mode

When preparing a new plan, `--recover-network --recover-compatibility` may now
be combined with repeatable `--preparation-root PATH`. The plan freezes those
authorized directories; execution cannot add or replace them. The recovery
controller searches each directory and its direct children, verifies matching
task, policies, archives and live image identities, then performs fresh reference
tests. Selected evidence hashes are recorded by the controller when consumed.
The directory is a search scope, not a guarantee that compatible assets exist.

Only successful reference verification launches the original task Agent, using
the recovered reference directory and its recipe-scoped build cache. A failed
discovery or recovery retains the original task/failure and never launches its
Agent; other predeclared batch tasks retain their existing execution behavior.
This setting is available only with both recovery flags. Without it, existing
batch behavior is unchanged. Old plans and scores are not migrated automatically.

The discovery and handoff checks are covered by `tests.test_swebench_batch` and
`tests.test_reference_pipeline`. Real discovery plus fresh reference scoring was
verified separately in `reference-discovery-live-v1`; the newly integrated batch
discovery-to-Agent path has regression coverage, not a new live model repair score.

For an explicitly exposed existing failure, the Python preparation API
`prepare_continuation` freezes one original task and its archived reference
failure. It does not rerun the initial failed grade or inherit a candidate patch.
The standard batch execution path then performs recovery and starts the original
Agent only after fresh reference acceptance. `--require-all-resolved` makes
execution exit nonzero unless every declared Agent runtime and official grade
passes. The prepared `recovery-agent-e2e-v1` experiment uses this path with
20 model calls / 180000 tokens, a 600-second recovery allowance and a 1200-second
Agent/final-grade allowance; its outer watchdog adds 60 seconds for containment.
It is a new exposed development attempt, not a resumed conversation or first score.
