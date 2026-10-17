# Adaptive role replanning

The adaptive strategy adds actual conditional role cycles to both native execution and LangGraph StateGraph. It preserves the original audit baseline, shared execution budget and frozen acceptance across all revisions. This is a runtime control-flow change; it does not generate or adopt changes to Keel's own source.

```json
{
  "mode": "localized-proposal",
  "recovery": {
    "strategy": "adaptive",
    "max_actions": 6,
    "repeat_limit": 2,
    "write_roots": ["src/library"]
  },
  "verification_repair_attempts": 3
}
```

The other existing goal/model/execution/acceptance settings are still required. `agent` mode is supported too. Legacy operator-localized `proposal` and explicit edit modes do not support adaptive replanning. The old `repair` strategy remains available and existing configurations retain their behavior.

## Failed verification routes

After failed acceptance, the host checks workspace changes, source invariants, JUnit identities and skip counts before invoking Critic. Policy/audit violations are terminal. Critic receives the original goal, a brief current plan, bounded test output and recent recovery decisions. Its only actions are:

- `repair`: revisit Implementer with current source and failed verification, keeping declared targets.
- `replan`: return to Scout and Planner to inspect current code and revise targets/approach within the host's original `write_roots`, then execute the revised plan.
- `stop`: record an explicit `recovery_stopped` failure. Critic cannot declare success or change acceptance.

Both orchestrators execute these as real nodes. Successful cycles still end in Verifier then Auditor. Lifecycle history and `orchestration.completed_nodes` retain repeated roles; LangGraph checkpoints contain the node sequence and budget after each completed node. There is no cross-process crash recovery claim.

Malformed Critic decisions get bounded host feedback, charged to the same recovery counter. Every Critic model call consumes the existing model/token/wall-clock budget. Repeated failure fingerprints and action limits stop further attempts. Up to the configured number of verification repairs are permitted; final failing acceptance never becomes success merely because the loop ended.

## Write boundaries and approvals

`write_roots` is an explicit host authorization, not a model suggestion. Roots must be existing repository directories and cannot escape the checkout. `.` explicitly authorizes the repository's existing non-protected Python sources; protected tests and internal metadata remain blocked. Initial and revised plans are checked against the same roots. Source catalogs in localized mode exclude targets outside those roots. No new source files, dependency changes or test changes are granted by this strategy.

Replanning preserves earlier workspace changes for inspection and correction. It does not blindly revert partial work. Previously touched files stay in the final audit even if omitted by a revised plan. Original bytes are retained on first authorization and never replaced with a post-edit baseline. Models may explicitly undo a mistaken edit after reading current evidence.

When `approval_before_write` is enabled, every revised plan goes through a new LangGraph approval interrupt before its Implementer runs. Requests bind the current workspace and revised plan hashes and include a revision number. Old decisions are retained in `approval_history`. Denial or workspace/config changes during approval stop new writes. A repair under the same approved plan does not expand its scope.

## Entry points

The automatic campaign enables adaptive routing under `write_roots: ["."]`; all protected-file policies still apply. For an existing package, prepare a fresh trial with `--adaptive-recovery --recovery-actions 6 --repair-attempts 3`. The runner derives host write roots from that package's frozen source scope; it does not ask the model to grant new permissions.

Example preparation (no model/Docker execution):

```powershell
python examples/run_transition_task.py --package .keel/task-packages/flask-login-issue5279-v1 --model-config .keel/model-openai.json --output .keel/transition-trials/flask-login-adaptive-v1 --strategy localized-proposal --baseline-feedback --require-change --max-context-bytes 24000 --repair-attempts 3 --recovery-actions 6 --adaptive-recovery
```

Then execute the frozen trial:

```powershell
python examples/run_transition_task.py --output .keel/transition-trials/flask-login-adaptive-v1 --execute
```

## Validation and remaining limits

Regression tests use scripted model responses with real source edits and acceptance subprocesses. They exercise wrong initial localization, correction of unrelated edits, fresh planning, model-budget exhaustion, explicit stop, write-root validation and repeated approval acceptance/denial. Native and real LangGraph node histories are compared, including actual checkpoint files. These establish control flow and guard behavior, not live model repair quality or a measured benchmark improvement.

Replanning cannot repair transport authentication, provision new services, exceed the operator's roots or weaken acceptance. A single oversized goal/definition/dependency payload can still exhaust capacity. The environment factory remains a separate bounded pipeline. Autonomous modification and adoption of runtime source code is not implemented.
