# Candidate representation 2x2 preflight

Implemented opt-in `encode_scoring_variant` with two independent settings:
`input_mode=numbered|without_ids`, `readout_mode=candidate_end|after_catalog`.
The shared experimental scoring instruction removes the generation schema in
all four cells. Candidate IDs remain in program-side identity records; the
ID-free model input contains no ordinal candidate IDs or ID enum. Definition
line numbers remain because they are source identities, not ordinal labels.

After-catalog mode appends label-free path/line/name readouts after the complete
catalog. Each readout can see that catalog, but still has causal readout-order
dependence. It repeats candidate content and increases compute; this is not a
pure visibility intervention. Teachers are not accepted by the encoder. The
existing default encoder/trainer/evaluator interfaces remain unchanged.

Real pinned offline Qwen tokenizer, 28 existing training presentations:

| Input | Readout | Longest tokens | Total tokens |
|---|---|---:|---:|
| Numbered | Candidate end | 3921 | 64064 |
| Numbered | After catalog | 8085 | 113772 |
| Without IDs | Candidate end | 3109 | 54548 |
| Without IDs | After catalog | 6463 | 94824 |

Evidence: `.keel/finetuning/scout-representation-preflight-v2/report.json`,
112 encodings with asset/dataset/implementation hashes, under a 90-second
`observed_stage` deadline. No GPU inference, training, download or hosted call.
v1 failed before encoding because the runner executes from its output directory
and the diagnostic assumed repository cwd. v2 explicitly derives and sets the
repository root; original failure and process receipts are retained.

16 focused regressions passed, including ID-free equivalence under renumbering,
after-catalog coverage, completion independence, common schema-free interface,
existing legacy alignment, score policy and calibration checks. These are not
full CI or quality results.

Before training: run a budgeted longest-input GPU forward/backward and memory
check. Do not silently truncate or swap representations on OOM. Then integrate
the representation policy into training/checkpoint/evaluation identity before
any training comparison. Old heads must not be relabelled as trained for these
new prompts. Freeze new evaluation presentations and the unchanged selection
policy before dispatch. The normalized numbered/candidate-end cell is the new
control: historical schema-bearing scores are not its paired baseline.

## GPU gradient feasibility completed

Shared `scout_representation_smoke.run` and `check_scout_representation.py` select
the longest full training input mechanically, validate the existing tokenizer
and pinned local weights, and run fresh strict-seeded rank4 q/v LoRA plus a score
head. All four cells ran in separate processes with 120-second enforced stage
budgets and progress receipts; total elapsed 114.203 seconds. No optimizer was
constructed or updated, and no checkpoint was promoted.

| Input | Readout | Tokens | Peak allocated GiB | Peak reserved GiB | Stage body seconds |
|---|---|---:|---:|---:|---:|
| Numbered | After catalog | 8085 | 2.273 | 2.656 | 36.141 |
| Numbered | Candidate end | 3921 | 1.707 | 1.924 | 23.610 |
| Without IDs | After catalog | 6463 | 2.050 | 2.363 | 23.797 |
| Without IDs | Candidate end | 3109 | 1.592 | 1.812 | 18.079 |

All losses and both LoRA/head gradients were finite, with nonzero gradient norms.
Evidence: `.keel/finetuning/scout-representation-gpu-v1/summary.json` and each cell's
`result/report.json`, recording input/source/weight receipt identities. This
establishes one backward's feasibility, not optimizer/checkpoint integration,
full-training memory stability, or improved localization. Sixteen related tests
passed after GPU stages; syntax checks passed.

One additional PowerShell launch during GPU work failed with HRESULT 0x800705AF;
the four existing GPU child processes completed successfully, and the shell and
checks worked afterward. The code denotes a host resource shortage, but its
specific contributor was not measured. This is separate from CUDA OOM and is
not evidence that the longest input failed. Prefer serial host-heavy checks and
record available host commit before future long GPU experiments.

Next: bind the representation policy into preparation, training, checkpoint and
evaluation identity, then run a tiny optimizer/save/load/evaluation smoke before
freezing a full comparison. Fresh aligned control training is required.

## Representation identity integration

The shared prepare/train CLI now accepts `--score-representation`:
`legacy`, `numbered_end`, `numbered_after`, `id_free_end`, `id_free_after`.
Nonlegacy policies require the `candidate_scores` objective. Preparation identity,
training receipt, head metadata and per-step metadata record the policy. Strict
recovery rejects changes; explicit preparation migration reuses verified weights
and dependencies while starting new base-model training. Missing historical
fields normalize to `legacy`.

Evaluation derives its encoder from training. An optional matching CLI policy
serves as an assertion, not an inference-time override. Parent/training/step
metadata must agree, including saved step.json for nonlegacy checkpoints; head
metadata is checked too. Reports retain the actual token-ID input hash in
addition to the original logical prompt hash. Position audits reject pairing
different representation policies.

The tiny interface protocol is recorded in
`.keel/finetuning/scout-representation-interface-v1/protocol.json`. It declares
one longest-first optimizer update per cell and seven original-presentation
scoring forwards after fresh checkpoint load. These scores test the interface
only and must not select a winning model or support a localization gain claim.

The interface protocol completed: all four preparations, optimizer steps,
checkpoint saves, fresh loads and seven-row scoring evaluations passed in
230.219 seconds. Each cell changed 112 LoRA tensors and both score-head tensors.
Total: four updates, 28 scoring forwards, zero hosted calls/downloads; no model
promotion. Every one-step cell scored 0/7 exact teacher sets. These untrained
smoke scores are retained, not evidence for choosing a representation.

47 related regressions passed (3.406 seconds), including legacy encoding
compatibility, representation override rejection before dispatch, parent/train/
step/saved-step policy drift rejection, and paired-audit policy mismatch. The
experiment records current source hashes and verifies they remain unchanged
between cells. Reused dependency and base-weight preparation is explicitly
recorded as migration, not optimizer resume or continuation of an old head.

Remaining work: freeze a full four-cell training/evaluation comparison before
running it. Hold query membership, LoRA configuration, logical exposure and
selection policy fixed, report token/compute differences, and freeze fresh
presentation hashes without fitting on their results. Existing exposed queries
still cannot establish independent task generalization or end-to-end repair.
