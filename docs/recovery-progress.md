# Recovery-round evidence feedback (experimental)

Enable `recovery.monitor_progress: true` only with adaptive recovery. The default
is false. The SWE-bench runner exposes the independent `--recovery-progress` flag;
it does not enable the pre-edit diagnostic inspection gate.

This connects an existing Critic next_check to subsequent evidence inventory and
verification observations. It adds no role, model request, permission, automatic
retry, stop rule or budget allowance. It does add bounded context to later Critic
requests, so token cost and capacity can change and must be measured. Existing
input-capacity checks remain authoritative; no request cap is silently raised.

## What is recorded

Each non-stop Critic decision opens a round containing its actual decision fact
ID, next_check question, tentative hypothesis and chosen route. On the next Critic
request, the host closes the round using ledger facts created after that decision:

- file/symbol observation references, with at most four summary previews and an
  explicit omitted-preview count; full evidence remains in the ledger;
- matching fresh verifier fact IDs, requiring every supplied verification result
  to match a new verifier receipt by payload identity;
- comparison of grouped failures only when both results have the same test-universe
  identity and group totals, using the existing candidate-ranking policy;
- an explicit unverified status for hypothesis truth and performance of next_check.

Comparison states are improved/regressed/tied for comparable grouped counts,
incomparable for fresh verification without comparable counts, and not_reverified
when no matching fresh verifier receipt exists. A supplied old result cannot make
an interrupted round appear revalidated. These states describe tested candidates,
not semantic progress or a root-cause proof.

The next Critic receives the prior round inventory and a short instruction to
review whether evidence answered the question, using its existing assessment
field. Model observations and conclusions remain untrusted. No extra schema fields
or extra model calls are needed. The monitor does not certify that cited source
was relevant, is still fresh, reached a model, or that the proposed check executed.
Its inventory is deliberately not a replay of source bodies.

On terminal success/failure the final pending round is closed before any earlier
candidate restoration. `result.recovery.progress.rounds` preserves the observed
candidate's verification status; restoration does not retroactively change it.
Progress start/review events and inventory facts are also recorded in trace/ledger.

## Evidence and next experiment

Focused checks cover matching/new versus old/unrelated verifier receipts, equal
test universes, evidence inventory without semantic overclaims, no extra model or
tool calls, final-round closure and an actual multi-round local repair using a
scripted model. Runner checks verify independent flag propagation and unchanged
reference network/plugin policies. These validate plumbing, not mini efficacy.

The preceding synthetic diagnosis pilot's apparent 2/4 versus 4/4 improvement came
from citation-protocol failures, not demonstrated better hypothesis selection.
Accordingly the monitor remains off by default. A next paired pilot must freeze a
new implementation/plan and measure actual task outcomes, costs and whether the
existing Critic's next_check is better grounded. Keep both arms' tool contracts and
protocol-correction opportunities identical. Do not rerun an old frozen plan after
this code change or treat a developer-known task as held-out validation.

No new real-model/Docker task was launched to validate this implementation.

## Prepared cost-bounded development pair

The shared coordinator examples/run_recovery_progress_comparison.py prepares a
fresh frozen plan and delegates both arms to run_swebench_task.execute. It does
not duplicate repair, environment recovery or grading. Preparation validates the
saved patch/feedback and reference, records input/implementation identities and
the selected host interpreter. Execution accepts only the prepared output path.

Local executable plan: .keel/repair-ablation/progress-v2/plan.json, using the already exposed
Astropy 14508 saved failure. Baseline runs first, then progress feedback enabled;
both keep pre-edit inspection off, candidate retention on, the same optional MCP
profile, acceptance and environment. Per arm: 12 model calls, 80,000 tokens, 80
tools, 900 Agent seconds. Combined Agent ceilings: 24 calls, 160,000 tokens,
1,800 seconds. Preparation and final grading remain separately bounded by the
existing runner and are outside these Agent totals. This is a short development
pilot, not comparable to historical 30-call runs or representative evaluation.

The task runner now permits only smaller positive integer budget overrides; its
defaults remain unchanged. It reports actual frozen limits for reuse validation.
Completed coordinator arms require matching trial, final-grading and trace hashes;
unchanged completed work is reused without inference. Interrupted/unreceipted
arms and model/infra errors stop without automatic paid retry. A runtime failed
repair with valid grading remains a measured failure, not an excluded result.

The comparison reports actual Critic dispatches carrying prior-round feedback.
Zero exposure means the experiment did not exercise the feedback mechanism; do
not infer benefit or lack of benefit from a treatment flag alone. Both-failed
outcomes have no efficacy winner. A single passed arm is a development observation,
not significance. Follow-up review should inspect whether the existing Critic
actually used observations rather than merely producing a longer explanation.

From D:\\keel, using the same Python interpreter recorded at preparation:

```powershell
& 'D:/code/monocular_depth_estimation/.venv/Scripts/python.exe' examples/run_recovery_progress_comparison.py --output .keel/repair-ablation/progress-v2 --execute
```

Do not edit implementation while this frozen pair is pending/running. If hashes
change, preserve this plan and deliberately prepare a new version; do not amend
the frozen identities in place. No paid execution has been launched by preparation.

The unexecuted progress-v1 preparation used the system Python, whose environment
lacks MCP. It is preserved as an invalidated preparation, not a failed Agent
attempt. The coordinator now checks MCP client availability before freezing and
before execution when a profile is enabled. Progress-v2 is bound to the existing
configured virtual environment; do not use a different host Python for it.

## Completed result

The prepared progress-v2 pair subsequently completed: both arms failed, with one
real feedback dispatch in treatment. No efficacy gain was established and the
default remains off. See [completed review](evaluations/recovery-progress-pilot-v2.md).
Do not repeat this completed pair to seek a better result; perform offline diagnosis
of handoff, contract interpretation and localization cost first.
