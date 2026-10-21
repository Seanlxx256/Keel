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
