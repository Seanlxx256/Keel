# Diagnostic inspection review and frozen ablation

No new model calls or Docker experiments were executed for this review.

## Historical development costs

These are different implementation revisions, not paired treatment/control runs.
All six selected Astropy continuation attempts are retained, including connection/infra failure.

| Run suffix | Model calls | Tokens | Intermediate grades | Nonempty final delta | Official outcome |
|---|---:|---:|---:|---|---|
| astropy-adaptive-inspection-20261021-124404 | 29 | 129,729 | 0 | False | False |
| astropy-adaptive-inspection-20261021-131803 | 25 | 115,523 | 0 | False | False |
| astropy-adaptive-inspection-20261021-134043 | 16 | 75,175 | 0 | False | False |
| astropy-adaptive-inspection-20261021-170544 | 5 | 15,391 | 0 | False | None |
| astropy-inspection-repair-20261021-121956 | 11 | 62,898 | 0 | False | False |
| astropy-transfer-repair-20261021-114707 | 28 | 154,424 | 3 | True | False |

Recorded total: 553,140 tokens / 114 model-call attempts. This excludes earlier unrelated Astropy development and is not a project-wide cost total.

No selected attempt achieved official resolution. Some fail before editing; a connection failure is not evidence of a code-test regression. Synthetic tests/context delivery improvements have not established repair efficacy.

## Low-cost replay

Historical run: astropy-adaptive-inspection-20261021-134043. Four covered read requests were reconstructed against old source/search receipts. Current context construction supplies a source body for each requested range. No saved model behavior or new repair result was simulated. This validates delivery only; it cannot predict whether mini will converge.

Artifacts: `.keel/repair-review/inspection-review-v1/historical-review.json` and `context-replay.json`.

## Frozen pilot comparison

Plan: `.keel/repair-ablation/inspection-v1/plan.json`. Fixed order: simple, inspection. Same saved Astropy source, failure evidence, mini configuration, optional MCP tools, retention policy, acceptance and per-arm budgets. Only pre-edit diagnostic inspection is switched off/on. One attempt per arm; two arms have a combined maximum of 60 model calls and 360,000 tokens, plus grading time. Actual costs must all be reported.

Run via `& .\.keel\repair-ablation\inspection-v1\run.ps1` only when ready. The script checks frozen inputs/implementation, skips completed arms, refuses to overwrite incomplete outputs and stops on infrastructure/model connection errors without paid retry. Both arms subsequently completed; results follow. The old script is now an archived frozen experiment, not a command to rerun after implementation changes.

If both fail, report no efficacy winner. If both pass, report costs descriptively. A single-task pilot cannot establish generalized or statistically significant gains. Do not keep/promote forced inspection solely because navigation metrics improved. Stop adding recovery mechanisms pending the comparison.

## Completed pair and engineering decision

Both arms passed frozen-input/configuration validation before the code default
changed. Same reported model gpt-5.4-mini-2026-03-17 and MCP configuration hash;
both used the same seeded source and budgets. Original plan/comparison/trials are
preserved under `.keel/repair-ablation/inspection-v1`.

| Arm | Official resolved | Model calls | Tokens | Intermediate verifications |
|---|---|---:|---:|---:|
| Simple continuation | false | 30 | 156,074 | 4 |
| Required inspection | false | 13 | 68,107 | 0 |

Both final reports have FAIL_TO_PASS 1/1 passing and PASS_TO_PASS 173 passing /
1 failing. The required arm stopped before editing; its lower usage is not a
measured efficiency gain while preserving successful repair. No efficacy winner
exists from this one-task pilot. The simple arm did make four distinct tested
source candidates. All retained the same rank [1 preservation failure, 0 target
failures]; the tie policy restored the earlier saved seed. Final source hash
matches the saved checkpoint in both arms. This validates real source restoration,
not improvement in repair quality. No external MCP calls were made in either arm.

Engineering decision: switch the standard task runner to inspection off by default;
retain explicit --diagnostic-inspection required for experimental use. This is a
complexity/default-policy decision under absent efficacy evidence, not proof that
simple continuation generally outperforms inspection. Existing Critic feedback,
source evidence, checkpoint retention, audit and independent grading remain.
The old frozen pilot must not be rerun with new code; any further controlled test
needs a new frozen plan. Completed evidence is archived rather than overwritten.

## Experience and prompt optimization direction

All six recorded inspection search queries were long multi-concept phrases even
though the tool performs literal matching; all returned zero matches. Offline
replay on copies of the same source found matches for an identifier extracted from
each query, six of six. No model or Docker calls were made. This validates the tool
contract and the examples, not causal root cause or improved Agent behavior.

Experience card: `.keel/experience/candidates/literal-search-contract-v1.json`.
It records trigger/applicability, failed queries, counterexamples, source hashes,
checks and limitations. Its state is candidate with verified tool observations;
it is not marked as a verified repair recipe or wired into automatic execution.
A versioned prompt candidate is recorded alongside it as literal-search-guidance-v1;
it is not deployed and has zero held-out examples. Valid literal phrases must not
be banned simply because they contain spaces.

Next optimization should evaluate this small tool-contract guidance on unseen
search cases before another full task. Keep candidate memory separate from verified
experience and keep development tasks out of independent evaluation. No vector
memory database, new supervisor, GEPA optimization run or model fine-tuning is
introduced as a consequence of this failed pair. We first need evidence that a
small, well-defined behavioral change improves tool use and then task outcomes.

## Search-guidance result and next diagnostic experiment

The real mini run in .keel/repair-review/search-guidance-model-v1 completed with
12 calls, 2,954 tokens and 96.234 seconds. Baseline scored 4/6 and candidate 6/6,
but both located all five present targets and correctly queried the absent target.
The two baseline failures concerned the boolean interpretation of zero hits,
not failed search requests. All raw replies match report records. Thus this run
does not reproduce or establish a fix for the historical prose-query failure.
Do not promote the prompt or claim repair gains from the aggregate 4/6 -> 6/6.

examples/evaluate_diagnosis.py is a separate, not-deployed diagnostic experiment.
Four synthetic cases form two twin families: the same initial symptom is produced
by two different component defects. The model receives the two hypotheses and a
fixed menu of executable boolean probes, but not the active cause, fixture source
or counterfactual oracle results. It predicts outcomes under both hypotheses,
requests a probe, receives its actual result, and can then conclude or check again.
Both arms share schemas and budgets; only the general diagnostic guidance differs.
This is a closed-menu, two-hypothesis task, not autonomous discovery of hypotheses,
arbitrary experiment design, code repair or a representative SWE-bench sample.

Passing requires the correct cause plus citation of a discriminating executed
probe whose predictions match both independently executed fixture variants. A
correct guess, repeated original symptom, invented citation or wrong predictions
cannot pass. The scorer does not establish the quality of free-text reasoning.
Each arm has at most three model turns and two distinct probes. Eight arms imply
at most 24 model calls and 128,000 tokens; request timeout is at most 45 seconds.
The stage deadline is 1,200 seconds per invocation. Local runs execute only fixed
standard-library fixtures through CommandRunner, never model-supplied code.

Use --resume only with identical manifest/implementation/configuration; completed
arms require a matching content receipt and are reused. Interrupted arms remain
incomplete and are not silently retried with a fresh budget. Unit checks use fake
models to validate execution, scoring, evidence visibility, repeat suppression and
resume without paid calls; those results are not real model performance. The mini
diagnosis comparison is prepared next, with no change to production reflection.

### Executed mini diagnosis pilot (2026-10-21)

The prepared status above is historical. The user subsequently executed
.keel/repair-review/diagnosis-model-v1. Manifest and implementation hashes match;
all eight completed-arm receipts, recomputed scores and fourteen raw replies were
checked. Baseline passed 2/4, candidate 4/4. Baseline used 3,068 tokens / six calls;
candidate used 4,698 / eight calls. Agent-arm wall times summed to 41.155 and
55.000 seconds respectively (not an independent end-to-end timing comparison).

Both failed baseline arms chose select_zero and correctly predicted false under A
and true under B. They were rejected before execution because evidence_ids named
original_failure, an available probe name rather than an observed evidence ID.
Thus failure was protocol compliance, not an observed incorrect causal diagnosis.
All eight first choices selected a discriminating probe with correct predictions;
all six arms that executed a probe then gave the correct conclusion and citation.
Conclude prediction fields are explicitly ignored by the frozen protocol and were
not retrospectively scored. Two twin families / one sample per arm cannot establish
general diagnostic improvement, and the treatment has greater observed cost.

Do not promote new reflection or claim a doubled diagnosis capability from 2/4 ->
4/4. A useful next test separates citation-protocol correction from diagnostic
guidance, under equal bounded feedback and new cases. For production, inspect
whether Critic next_check becomes an actual observation and changed hypothesis,
rather than adding another mandatory inspector based on this pilot alone.
