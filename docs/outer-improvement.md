# Bounded outer improvement MVP

`examples/run_outer_improvement.py` proposes up to three generic **guidance strings**, then evaluates the incumbent and each candidate on the same four synthetic diagnosis cases using the existing isolated fixed-probe executor. Candidates cannot replace probes, labels, scoring, permissions or budget configuration. Oracle outputs stay outside model requests. Each arm has at most three turns and two distinct probes; replies have a 2048-token allowance. Alternating arm order reduces a fixed-order artifact but is not repeated statistical evaluation.

One shared budget covers proposal and all arms: 49 model calls, 260000 tokens, 96 child probe calls, at most 900 seconds. These are ceilings, not a promise to consume the full allowance. Provider failure remains incomplete; it is not assigned a zero score. Structured protocol violations are failed diagnosis outcomes. Each provider dispatch and raw response is checkpointed, with per-turn progress and bounded provider/child timeouts.

Selection requires strictly more grounded passes and no loss on any case the incumbent passed. Ties and regressions retain the incumbent. The result is **provisional**, always `production_promoted=false`; no production configuration is written. Labels and fixed probes provide objective checks of predictions, conclusions and citations, not semantic certification of arbitrary prose.

Run from repository root:

```powershell
& 'D:\code\monocular_depth_estimation\.venv\Scripts\python.exe' examples/run_outer_improvement.py --model-config .keel/model-openai.json --output .keel/outer-improvement/pilot-v1
```

Add `--resume` to reuse completed arms only when configuration, fixtures, implementation, proposal and arm receipts match. Usage and elapsed budget carry forward. Incomplete/dispatched arms are preserved and refused; automatic paid retry is disabled. Changing implementation requires a new output, not silently reusing old results.

This first harness uses exposed developer-authored cases in two families, not independent selection or held-out repository tasks. Proposal feedback is currently a fixed generic developer summary, not automatic trajectory mining. A scripted-model regression validates proposal → real child execution → objective comparison → reject/retain, including no-paid-call resume; it does not demonstrate improvement by a live LLM. Next qualify with a bounded live run, then add independently constructed selection cases and repeated controls before production promotion or claims of recursive self-improvement.

## Frozen-prompt validation v2

Use `--validate-pilot .keel/outer-improvement/pilot-v1` with a new output. This checks the completed pilot's manifest, model configuration, proposal and arm receipts, and copies all three prompt strings unchanged into the new manifest. It makes no new proposal call. The original pilot files are not rewritten.

New versioned cases in `keel/outer_validation_cases.py` cover routing-resolution versus transport redirection, and save-time aliasing versus restore-time mutation. Each family has identical initial symptoms under two hidden causes, mechanically checked by real fixed subprocess probes. Both causes plus the old counter-B control run twice: 10 case/repetition slots per arm, four arms, 40 trials. The two repetitions reverse arm order. This is a small repeat check, not a confidence interval or a large-scale stability claim.

All arms receive the same explicit observation-ID and boolean-prediction contract. This is a changed evaluator, so v1 and v2 rates are not directly comparable. The legacy evaluator default remains unchanged. New reports separate protocol failures, correct conclusions, correct counterfactual predictions and grounded passes; `eligible_tied_best` makes tie-breaking visible. Per-slot non-regression remains the provisional gate. Full trajectories stay in each trial directory.

Validation has one aggregate ceiling: 900 seconds, 120 model calls, 260000 tokens, 160 fixed child probe calls. No production promotion; no new model training. These developer-authored synthetic families were constructed after the prompts were frozen and are not given to the proposer. They remain related compositional diagnosis problems, not independently curated repository tasks or proof of general repair transfer.

```powershell
& 'D:\code\monocular_depth_estimation\.venv\Scripts\python.exe' examples/run_outer_improvement.py --model-config .keel/model-openai.json --validate-pilot .keel/outer-improvement/pilot-v1 --output .keel/outer-improvement/validation-v2
```

## Failure-guided narrow replay

`--feedback-from .keel/outer-improvement/validation-v2 --max-seconds 300` verifies the completed validation manifest, model configuration, proposal receipt and every arm receipt/score before dispatch. It selects the first two distinct failing families and one passing incumbent control from another family. Current inputs select routing-A, snapshot-B and counter-B. Selection is deterministic from results; no business-specific correction is supplied.

The proposer receives the original public hypotheses/probe expressions, recorded model steps, actual observation IDs/results and measured outcome flags. Hidden fixture sources, oracle truth tables and host cause labels are excluded from this request. It can propose at most one general guidance string. The incumbent and candidate then start fresh on the three exposed cases with identical evidence-ID rules and unchanged scoring. This is a small development replay of case conditions, not continuation from exactly the same internal model state or proof of independent transfer.

Aggregate ceiling: 300 seconds, 19 provider calls, 24 fixed child calls; the existing conservative 260000-token ceiling also applies. At most seven solver/proposer stages with the usual per-stage progress/timeouts. Raw replies, required checkpoints, completed-arm reuse and shared cumulative budget remain in effect. Resume compares canonical persisted JSON, so tuple/list representation changes cannot falsely invalidate identical specs. Incomplete calls are preserved and not automatically repeated. The existing scorer still requires correct pre-execution predictions and a grounded final conclusion; it is not relaxed to make a candidate pass.

```powershell
& 'D:\code\monocular_depth_estimation\.venv\Scripts\python.exe' examples/run_outer_improvement.py --model-config .keel/model-openai.json --feedback-from .keel/outer-improvement/validation-v2 --max-seconds 300 --output .keel/outer-improvement/feedback-replay-v1
```

Even if a candidate wins, no production policy is installed. These examples are now proposal feedback/development data. Future improvement claims require a new selection set that the proposer has not received.

### Reuse a saved proposal after an identifier-validation fix

Candidate IDs are safe ASCII identifiers of at most 64 characters, shared by schema and host validation; path separators and reserved/duplicate names remain forbidden. IDs are metadata, not diagnosis content. A 26-character live proposal exposed the former arbitrary 24-character cap.

`--reuse-proposal OLD_OUTPUT` requires an incomplete pre-trial proposal with exactly one recorded model call, known matching token usage, no tools or trial directories, identical protected inputs/limits and a now-valid saved response. A new output records source-file identities and previous implementation identity as an explicit migration. It copies the raw proposal unchanged, carries prior calls/tokens/elapsed time, and starts solver comparisons without another proposal dispatch. Ambiguous/incompatible states are refused. The original failed directory is unchanged. This is explicit reuse across implementation migration, not relaxed ordinary resume or evidence of repaired diagnosis.
