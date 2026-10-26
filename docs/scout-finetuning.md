# Scout fine-tuning: data before training

The first proposed target is the LLM selecting files/locations for Scout, not
Compass's index, embedding model or ranking algorithm. No model has been trained
by this increment. Existing Keel behavior and model configurations are unchanged.

## Current implemented step

`examples/audit_scout_data.py` reads existing frozen-model JSONL transcripts and
adjacent bounded `trial.json` metadata. It makes no model, Docker or embedding
calls, installs nothing, and emits metadata rather than raw prompts or targets.

It pairs request/response events, inventories provider errors and incomplete
calls, and identifies `files`/`locations` response schemas. These schemas suggest
Scout localization, but role attribution still requires review. The shape/count/
item-type/enum checks are not a complete JSON Schema or runtime-policy validator.
In particular, a path being readable does not make it an authorized edit target;
`locations` without a schema enum need separate source-structure checks.

Outputs:

- `report.json`: source/implementation hashes, scope, exclusions and counts.
- `candidates.jsonl`: source line references, input/schema/target fingerprints,
  limited provenance and review requirements; no raw prompt/target export.
- `progress.jsonl`: shared progress/heartbeat implementation.

Every candidate has `training_approved: false`. A successful final task does not
prove each intermediate localization is correct. Human-assistance status remains
unknown unless independently established. No train/validation/test split is made.

```powershell
python examples/audit_scout_data.py --root .keel/swebench --root .keel/repair-review --root .keel/repair-exploration --output .keel/finetuning/scout-audit-NEW --timeout 120
```

Choose a new output; preserve old reports. Source roots are explicit, traversal
skips snapshots, checkouts, environments and datasets, and does not follow
symlinks/reparse points. File/line resource exclusions are recorded, not truncated
into fabricated examples. Deadline failures produce an incomplete receipt. Required
result failures remain errors; progress failures do not invalidate completed work.
Sources and adjacent metadata are rechecked before publishing completion.

## Observed inventory, 2026-10-26

`.keel/finetuning/scout-audit-v2/report.json` completed in 3.344 seconds, zero model
calls, across the three roots above:

| Observation | Count |
|---|---:|
| Transcripts | 61 |
| File/location selection responses | 219 |
| Shape/count/enum-screened responses | 214 |
| Structurally rejected responses | 5 |
| Exact duplicate examples | 7 |
| Unique review candidates | 207 |
| Task IDs represented | 6 |
| Approved training examples | 0 |

Candidate distribution: Astropy14508 131, Matplotlib24627 35, Sphinx9602 22,
pytest7432 12, Matplotlib24026 5, xarray4629 2. These are observed task IDs, not
certified independent repositories or a clean evaluation split.

Among the 207 unique candidates, 139 come from source-continuation attempts and
64 have a historical diagnostic-report receipt. Seven contain empty selections.
Nine identical input/schema states have different target outputs. Empty selections
and different answers are review priorities, not automatic errors or preference
labels. Input text ranges from 1,884 to 41,182 characters; these are not token counts.

This is heavily concentrated development data, not 207 independent successful
examples. Existing parent task outcomes do not certify semantic relevance,
human-intervention absence or reference-answer cleanliness. Treat existing exposed
cases as development material; collect independent tasks for later evaluation.

## Next stages, not implemented yet

1. Review a small task-stratified sample plus rejected/empty/conflicting cases.
   Reopen each original transcript only after hash verification; inspect what was
   known before the action, candidate visibility, writable/read-only scope and
   actual source relevance. Record reviewer, rationale and evidence, including
   exclusions; do not rewrite original outputs as though the teacher produced them.
2. Build a versioned, explicitly reviewed SFT exporter with input/schema/target
   provenance. Preserve task grouping and near-duplicates before splitting.
   Keep reference-answer metadata and future tool results out of model inputs.
3. Select a trainable open model after GPU/context measurements. First verify a
   tiny training pipeline, target loss masks and adapter save/load. This is a
   training smoke check, not generalization evidence.
4. Compare the same base model before/after SFT on independent localization states,
   then plug the adapter into Scout only. Keep other roles/tools/budgets fixed;
   report end-to-end repair outcomes, cost and regressions.

Do not start by mixing all roles, training on whole successful runs indiscriminately,
or treating failed runs as universal negative preferences. DPO and automatic
adapter promotion require separate validated data and experiments.

Regression checks: `tests.test_scout_data_audit`; related frozen-model logging
checks: `tests.test_campaign_reporting` and `tests.test_frozen_model_review`.

## First review increment, 2026-10-26

`review_scout_data.py` verifies the audit/queue/transcript/metadata identities
before reviewing selected events. It checks exact visible symbol IDs (not merely
schema shape), page carry, and the shared current `protected_path` policy. It
does not modify historical outcomes or automatically label semantic relevance.

```powershell
python examples/review_scout_data.py --audit .keel/finetuning/scout-audit-v2 --queue .keel/finetuning/scout-audit-v2/review-queue.json --output .keel/finetuning/scout-review-NEW --timeout 120
```

Actual `scout-review-v1/review.json` completed 44 queued items in 1.359 seconds,
zero model calls: 11 excluded under current contracts, 10 held for provenance,
23 needing semantic review. This selected queue overrepresents problematic states;
these proportions must not be extrapolated to all 207 candidates.

Important findings:

- Some location responses satisfy a string-array schema but guess definition
  lines not present in the supplied structure.
- Legacy pytest selections include a test file allowed by an older catalog but
  protected by current write policy. Exclude them from current-target training
  without rewriting their historical run scores.
- A page selection is not final global localization. Empty pages may explicitly
  mean retain previous choices; older instructions leave that interpretation
  unverified. Do not teach every empty page as a failure.
- Same-state alternative targets are not automatically positive/negative pairs.

Developer inspected the first twelve task-stratified inputs and independently
read base-commit Git objects for four xarray/Sphinx selections, recording source
and input-receipt hashes. `developer-assessments.json` separates these judgments
from automated triage: 4 approved **development smoke controls**, 19 remaining
semantic reviews, 10 provenance holds and 11 current-contract exclusions.
The four outputs are unchanged teacher selections. Their goals match the original
input receipt; selected symbol IDs match base definitions. This establishes
relevant scope, not minimal/optimal choices, unassisted task provenance or held-out
eligibility. The xarray issue itself supplies location/fix hints and is an easy
control, not an autonomous diagnosis benchmark.

No raw SFT file has been exported and no weights updated. Next build an explicitly
review-gated exporter for those development controls and verify target masking;
independent evaluation needs new tasks. GPU/model selection is still pending.

## Reviewed development export, 2026-10-26

`export_scout_sft.py` now exports only explicit `approved_development_smoke`
decisions whose raw targets are unchanged and whose scope remains development-only.
It rechecks the review receipts, exact original event pairs, goal receipt, shared
selection contracts and immutable base-commit source bytes. Source evidence is
read using command-local Git settings, never the mutable final worktree.

```powershell
python examples/export_scout_sft.py --review .keel/finetuning/scout-review-v1 --output .keel/finetuning/scout-sft-dev-NEW --timeout 120
```

Actual `scout-sft-dev-v1` exported 4 examples in 1.281 seconds: 2 xarray and 2 Sphinx.
`development.jsonl` contains conversational `prompt`/`completion` pairs. Teacher
completion text remains byte-for-byte the same string; no future tool event,
reviewer's rationale, reference patch or run report is appended to model inputs.
Unlike the metadata audit, this explicit export contains the reviewed raw inputs
locally under ignored `.keel/`; it is not automatically published or uploaded.

The external request JSON schema is made visible in the system message using
`training_prompt` and version `scout-request-schema-v1`. Original message contents
are preserved with this declared schema suffix. A future local Scout inference
adapter must use that same function; existing hosted-model runtime is unchanged.
`export.json` records source/implementation/input and output identities, sample
IDs/task groups, approval identity and development-only scope. No train/test split
is invented from these two exposed tasks.

`completion_labels` takes IDs and a completion mask from a **single full template
encoding**, masks prompt positions with -100, and leaves target IDs unshifted.
The causal language model should handle its normal shift once; tokenizing prompt
and response independently is not assumed equivalent to tokenizing the full chat.

`mask-fixture.json` verifies this algebra using deterministic character positions
only. It explicitly reports `real_model_tokenizer_verified: false`. This is not
proof of a selected model's chat-template boundary, SFTTrainer masking, gradient
flow or training success. The target-tokenizer check remains pending model choice.

Observed input lengths after schema inclusion: xarray files 9,480 characters,
xarray symbols 4,531; Sphinx files 13,136, Sphinx symbols 5,506. These are not token
counts. No sample was silently shortened to meet a hypothetical model budget.

Hardware query found NVIDIA GeForce RTX 3050 Laptop GPU, 4,096 MiB total VRAM.
The queried harness Python has no torch/transformers/TRL installed. This observes
hardware and dependencies only, not a CUDA allocation or feasibility measurement.
No package/model download or training was dispatched. Next select and pin a small
model/tokenizer, measure actual lengths and memory, then verify full-template target
masking before any optimizer step. Samples too long for a measured budget require
an explicit data/context decision, not removing decisive evidence silently.

Regression checks: `tests.test_scout_sft`, `tests.test_scout_data_review` and
`tests.test_scout_data_audit`: 26 checks passed, including a real temporary Git
base-object read with a deliberately changed worktree, approval scope escalation,
source drift, exact target preservation, future-event exclusion and mask logic.


## Pinned real tokenizer preparation (pending live execution)

Use Qwen/Qwen3-0.6B revision c1899de289a04d12100db370d81485cdf75e47ca
with transformers==4.57.6 and jinja2==3.1.6 in a new dedicated environment.
The official model template supports enable_thinking=False; use that same setting
for full-conversation rendering and generation prefill. Only config.json,
tokenizer.json and tokenizer_config.json are downloaded; no model weights.
See https://huggingface.co/Qwen/Qwen3-0.6B for the model/template documentation.

prepare_scout_tokenizer.py uses a 600-second shared deadline and stage receipts.
Completed environment and asset receipts can be reused with --recover-from into a
new output after dataset/configuration/interpreter/package/asset checks. Prior
results are preserved. Process logs never overwrite semantic asset/check receipts.
The check uses offline local files, no remote code, a single full-template encoding,
offset-boundary verification, generation-prefix agreement and completion/EOS labels.
It does not truncate examples or certify GPU training feasibility. The six new
regressions use fixture tokenizers/processes, not the real downloaded tokenizer.

The developer environment already has torch 2.5.1+cu121 and reports CUDA available;
the harness environment lacks torch. Neither existing environment is modified.
Observed D: free space was about 10.66 GiB. A tool-host HTTPS probe to Hugging Face
was refused (WinError 10061); no authentication or model failure established.
Use the frozen user-terminal launcher for the actual preparation check. No API key
or Docker is required. Four exposed controls remain development-only data;
no optimizer steps, weight updates, heldout evaluation or model improvement yet.


### Live tokenizer result (2026-10-26)

scout-tokenizer-live-v1 passed: preparation 158.157s, watchdog 160.046s.
Environment/check/assets and original dataset hashes revalidated. Real input
lengths: 3072, 1652, 3936, 2288 tokens; completion/EOS labels: 12, 38, 30, 62.
All four full templates preserve targets and generation prefill, without truncation.
This supersedes pending tokenizer validation above. No weights downloaded or
optimizer steps executed; next verify bounded LoRA forward/backward GPU memory
on full examples. This is still four exposed development controls, no heldout score.


## First bounded LoRA resource smoke (prepared, not executed)

The next run uses the same pinned Qwen3-0.6B weights, downloaded to a retained
Hugging Face cache without duplicating the multi-GB file. Weight hashes stream in
1 MiB chunks. A new environment installs transformers==4.57.6, peft==0.17.1 and
jinja2==3.1.6; an explicit .pth entry reads the existing developer site's
Torch 2.5.1+cu121 and dependencies. This is an explicitly shared read-only dependency
source, not a fully hermetic environment. Installation targets only the new venv;
existing developer/harness/tokenizer environments are not modified. Package
inventory and imports/CUDA are checked before weight download.

The shared preparation deadline is 1800s, outer containment 1860s; individual
install/download/train caps are 300/900/600s. Explicit --recover-from validates
inputs/environment/weight receipts and reuses completed preparation in a new
output. It restarts the four-step smoke from base; it does not silently resume
optimizer state or count old training as current success. Partial downloads retain
the same cache. Prior outputs and per-stage logs are preserved.

LoRA rank4, alpha8, dropout0 targets q_proj/v_proj, AdamW lr1e-4, seed42,
float16 base, SDPA and nonreentrant gradient checkpointing. Batch size1, longest
sample first, four full examples once, no truncation/packing. Computing the LM
head only at hidden positions predicting labelled targets avoids prompt vocabulary
logits. Causal cross entropy shifts once; a real Torch CPU test compares both loss
and gradients with conventional full-logits masked causal CE. This is a memory
optimization, not removing prompt context or changing training labels.

Each step requires finite loss and nonzero finite gradient norm, checks adapter
parameter changes, and saves a separately hashed adapter/optimizer checkpoint plus
loss/peak allocated/reserved GPU memory. Only LoRA parameters may be trainable.
No CPU fallback or automatic shortened sample is allowed after CUDA OOM. Such a
result is a resource observation, not a task-quality failure. Checkpoint directories
are finalized by rename; interrupted temporary saves are not completed checkpoints.
No TRL Trainer, inference quality evaluation, Keel model replacement or heldout
claim is included. Four exposed controls are insufficient to show model improvement.

Implementation: keel/scout_lora.py, keel/scout_training_setup.py,
examples/run_scout_lora.py. PEFT API reference:
https://huggingface.co/docs/peft/package_reference/lora . Real GPU result pending.


### LoRA v1 preflight correction

v1 stopped before downloading weights: a last-wins distribution inventory mistook
shadowed developer Jinja2 3.1.4 metadata for the actually selected newenv 3.1.6.
Import and metadata.version verified 3.1.6. Corrected inventory uses selected
distributions; pins remain unchanged. Real corrected preflight in the original
newenv passed (Torch/CUDA, Qwen3/PEFT imports and inventory). No reinstall required.
scout-lora-smoke-live-v2 explicitly recovers that completed install into a new run;
old output/failed result preserved. RequestsDependencyWarning remained nonfatal;
no GPU training or weight download has yet occurred.


### First real GPU update result (2026-10-26)

v2 completed environment and weight download but OOMed at the first 3936-token
attention forward, before any updates. This was not a deadline or token limit.
A real GPU probe found Flash unavailable in this Windows Torch build while
Efficient Attention supports forward/backward. The pinned Transformers GQA route
used enable_gqa=True; explicit KV repetition allows the efficient kernel with
unchanged grouped causal attention. A named attention registration includes the
standard SDPA mask mapping and forces Efficient on CUDA, with no math fallback.
Numerical/gradient tests and a tiny actual Qwen3+LoRA checkpoint backward passed.

Developer then ran frozen scout-lora-smoke-live-v3 directly using retained weights
and environment: watchdog 40.031s, preparation 35.766s, training 12.125s, passed.
All four full samples completed an optimizer update, with 112 adapter tensors
changed per step and finite nonzero gradients (573440 trainable parameters).
Maximum PyTorch allocated memory 1814376448 bytes (1.690 GiB), reserved memory
2055208960 bytes (1.914 GiB). These are allocator peaks, not total device usage.
All four finalized adapter/optimizer checkpoint file hashes and the final training
receipt were checked. Original v1/v2 failures remain preserved. No reinstall or
weight redownload was necessary, no sample shortening or model switch.

Loss values across the four DIFFERENT samples are not a loss reduction curve.
This result establishes GPU training mechanics and measured capacity only, not
Scout quality, Keel repair improvement, independent generalization or production
promotion. Next compare base/adapter under the same inference contract and collect
independent evaluation examples before claiming a training benefit.


## Paired base/adapter development evaluation

scout_adapter_eval uses the exact same four exposed controls, pinned model,
nonthinking generation prefill and final step-4 adapter. Inference uses one frozen
PEFT model with adapter disabled for the base arm, enabled for adapter; eval mode,
greedy generation, full prompt, max256newtokens/45spergeneration. Output caps are
reported as censored, not silently retried or repaired. Prefix-only input excludes
teacher completion. logits_to_keep=1 avoids prompt vocabulary-logit allocation;
cache and the verified Efficient repeated-KV attention backend are enabled.

Raw generated text is retained locally. Shared Scout schema/catalog/protected-path
checks distinguish valid JSON, valid selection contract and agreement with reviewed
teacher sets (order-independent). No grammar constraint or fence-stripping rescue.
Teacher-token NLL is computed separately on identical full examples for both arms,
aggregated by labelled-token count rather than averaging unequal samples. It is a
training-control metric, not heldout generalization. Generation timing is descriptive:
base always runs first, so it is not a randomized latency experiment.

The required report is updated after every sample/arm; model failure is incomplete,
not zero-quality benchmark score. Both original training/checkpoint receipts and
files are verified before evaluation; dataset/checkpoint freshness rechecked at end.
Adapter outputs never promote a production model automatically. Checkpoint scores
on these four training examples cannot establish semantic optimality or repair gains.


### Live paired result and scorer correction (2026-10-26)

Developer executed scout-adapter-eval-live-v1: eight generations completed,
watchdog70.031s/evaluation56.078s, no training or new downloads. Initial JSON-valid
metric incorrectly meant JSON-object; corrected scorer distinguishes syntax and
object validity. scout-adapter-eval-rescore-v1 reuses all original raw generations,
records original report/scorer hashes and performs zero new generation calls.
Original evaluation artifact is preserved. Seven scorer/rescore tests pass.

| Development metric | Base | Final four-step adapter |
| --- | ---: | ---: |
| Syntactically valid JSON | 0/4 | 4/4 |
| Valid selection contract | 0/4 | 1/4 |
| Reviewed teacher selection set matched | 0/4 | 1/4 |
| Censored by generation limit | 2/4 | 0/4 |
| Teacher-token weighted NLL | 1.177724 | 0.901955 |

NLL decreased23.4154percent on training controls, not heldout tasks. Base already
selected the correct xarray file inside a Markdown fence; adapter removes the
fence. The strict agreement gain here is principally formatting adaptation, not
proof of improved localization reasoning. Symbol generations still violate shape
or exact identifiers; Sphinx file generation enumerates23items despite max8.
Two base generations hit256tokens; censored outputs are explicit. Larger output
caps would not undo the already-invalid enumerations. No model promotion.
Before interpreting gains, expand reviewed task diversity and preregister a split
by task/repository; these four exposed controls cannot supply a heldout score.


## Expansion triage and frozen task-group reservation (2026-10-26)

Full offline contract review now covers all207unique schema-screened candidates:
119provenance holds,26contract exclusions,62pending semantic review,0new approvals.
This does not replace the four prior developer-approved controls.

scout-data-reservation-v1 declares task groups before additional training:
Astropy131quarantined; both Matplotlib24026/24627 tasks40reserved together for
transfer review; xarray/Sphinx/pytest36training-side candidates. Among62passing
contract review,22are training-side (4already used,18potential new examples),
40are transfer-side. None of the new18or40is approved yet. The source grouping
is explicitly declared, not inferred proof of canonical repository identity.

scout_data_split rejects same-group partition leakage, previously trained task
reclassification, same input state across roles, missing assignments and changed
sample evidence. Required manifests bind audit/review/export/original dataset and
review source evidence. Five regressions pass; actual reservation completed offline.
No raw examples exported, targets rewritten, training run or automatic approval.
All these tasks are exposed public development cases. A transfer reservation is
not a blind heldout score; genuinely new tasks and provenance review remain needed.
Next review source correctness and assistance for18training-expansion candidates
and40transfer candidates before expanding the corpus or comparing more epochs.


### Source-level expansion review (2026-10-26)

All18training-side new candidates inspected against original messages, goal receipts
and immutable Git base sources.14goals already include verification/Critic feedback;
three symbol selections contain four line IDs that no longer match base definitions.
Sidecar flags alone missed this. The generic contract review now holds known embedded
verification blocks for intermediate-source provenance review. This is not a blanket
ban on recovery data: bind exact per-round source before approving that cohort.

Developer approves only two new unchanged pytest initial file/symbol targets.
The original issue explicitly hints skipping.py/pytest_runtest_makereport, making
these hinted development controls.14feedback candidates held; one redundant Sphinx
file control excluded from additional weighting; one broad symbol bundle remains
unapproved. scout-semantic-review-v2 stores facts separately from developer decisions.
scout-sft-dev-v2 exports6pairs across3tasks, retains4prior approvals, no Matplotlib
transfer targets included. Real offline tokenizer passed6full examples at
3072/1652/1860/673/3936/2288tokens; no additional GPU training or downloads.
The existing adapter remains trained on the old four controls.

Full207recheck v2 supersedes earlier triage counts:153provenance holds,
28semantic pending,26contract exclusions. Reservation group roles unchanged:
40Matplotlib transfer candidates total,20still passing current provenance/contract
triage;8training-side pending include6approved controls and2held/redundant examples.
Next source-review20transfer candidates before another train/evaluate cycle.
No independent unexposed heldout dataset is established.


### Reserved transfer controls and actual negative result (2026-10-26)

Final20candidate stage count is15pages and5nonpaged records, correcting the
preliminary14/6verbal count. Exclude15pages from this final-localization cohort,
retain two representatives (one per task), and exclude three repeated task records.
This does not label page actions semantically wrong or permanently unusable.
The first developer review script rejected a valid empty __init__.py in an already
ineligible page; failed attempt preserved. Revised stage-first review verifies all20
goals/stages and five nonpaged records against immutable base sources.

scout-transfer-dev-v1 contains2unchanged symbol-selection examples for24026and24627,
explicitly evaluation-only, not part of the six-example training export. Guards
prevent task/group overlap with training, page-as-final labels, forged task IDs,
receipt/base drift or independent-eligibility upgrade. The cohort is exposed
public development data, not a blind heldout benchmark.

The paired evaluator now supports a separate evaluation dataset while retaining
original training/tokenizer/checkpoint identity checks. Existing old four-step
adapter was evaluated without further training or downloads:
scout-transfer-eval-live-v1 completed4generations in20s (watchdog40.031s).
All generated EOS; prompt lengths1016and6933tokens, no truncation or cap censoring.

| Exposed transfer metric | Base | Old four-step adapter |
| --- | ---: | ---: |
| Valid JSON syntax | 1/2 | 1/2 |
| Valid localization contract | 0/2 | 0/2 |
| Reviewed teacher set matched | 0/2 | 0/2 |
| Teacher-token weighted NLL | 1.123076 | 0.987347 |

Lower NLL (about12.1percent) did not improve generated decisions. Both models emit
the same fenced/extra-ID stackplot answer; the other case yields an empty array
or an invalid-ID array. Preserve this negative finding. Runner completion is not
model acceptance. Current evidence shows training mechanics and limited formatting
adaptation, not localization transfer or Keel repair improvement. The approved
six-example expansion has not yet been trained; independent unseen data remains
absent. Further model work must preregister training/selection and preserve this
baseline, rather than repeatedly tune and relabel these cases as independent tests.


## Predeclared six-example epoch comparison

scout-epoch-comparison-v1/protocol.json was frozen before dispatch: fresh base
weights, six approved development controls, seed42, rank4/alpha8, lr1e-4,
batch1, longest-first order repeated, four epochs/24updates. Both step6(oneepoch)
and step24(fourepochs) are evaluated on six training controls and the two exposed
Matplotlib transfer controls. No best-checkpoint selection, target changes,
early-success stopping or automatic production promotion. Existing old-four-example
baseline remains preserved; this same-six-example comparison isolates training
rounds rather than attributing old/new dataset differences to epochs.

Completed environment/weight preparation is migrated explicitly across changed
data/epochs, while strict --recover-from still rejects configuration drift. Fresh
training starts from base, not the old adapter or optimizer. Epoch count and sample
count determine expected steps; no four-example constant. Completed real tokenizer
check metadata is reconstructed in a new receipt, explicitly not a fresh tokenizer
execution. Early endpoint checkpoints are hash-validated against the completed run.

Generation remains greedy/nonthinking,256newtokens/45s, original scorer/case targets.
Within the same completed training receipt, later endpoint evaluations may reuse
base-arm rows only after matching cohort, generation configuration and completeness;
historical timings remain labelled as reused. No duplicate base calls are needed.
The combined experiment has900s shared stage budget,960s outer containment;
individual child deadlines and heartbeat/process receipts remain enforced.


### Fixed endpoint results (2026-10-26)

Experiment completed250.031souter/243sdriver; training49.61s,24updates/checkpoint
hashes verified, maxallocated1.6968GiB. Protocol and all four endpoint reports
hash-verified. One/four epoch checkpoints both reported; no chosen winner/promotion.

| Metric | Base | 1 epoch | 4 epochs |
| --- | ---: | ---: | ---: |
| Training valid JSON | 0/6 | 5/6 | 6/6 |
| Training valid contract | 0/6 | 2/6 | 4/6 |
| Training teacher set matched | 0/6 | 2/6 | 2/6 |
| Training teacher-token NLL | 1.255265 | 0.847160 | 0.291670 |
| Transfer valid contract | 0/2 | 0/2 | 0/2 |
| Transfer teacher set matched | 0/2 | 0/2 | 0/2 |
| Transfer teacher-token NLL | 1.123076 | 0.909242 | 0.547481 |

All adapter generations finishedEOS; three base-training generations hit256tokens
and remain markedcensored. Four-epoch transfer generations are validJSON but
incorrect identifiers/keys: stackplot uses issue-trace line numbers as definition
IDs; the other copies IPython example text. Lower mean tokenNLL can reward syntax
without getting the decisive identifier right. This is format adaptation, not
established localization transfer. Cached verified base arms saved8generationcalls;
24new local generations, no hosted provider calls. No blind independent score.

Next proposed controlled ablation: freeze weights and compare explicit candidate
IDs with free path/line construction, retaining the same targets and wrong-choice
metrics. This is proposed only; no case-specific answer repair or extra epochs.


## Frozen candidate-ID interface ablation (2026-10-26)

Fixed checkpoint24, unchanged3training-symbol/2transfer queries, same greedy
256token/45scaps. Ordinal IDs generated from original catalog order only; matching
schema/instructions and third tuple field added, all original goal/catalog/source
metadata retained. No decoder constraints, training, label-based prompt selection,
nearest-ID projection or silent truncation. Output IDs map deterministically to
canonical locations; legal but wrong choices remain wrong. Fourteen focused tests
pass. Existing free-path generations were identity-checked/reused;10newlocalcalls.
Actual run completed100.016souter/93.375sdriver, protocol/source hashes verified.

| Adapter strict metric | Free path/line | Candidate IDs |
| --- | ---: | ---: |
| Training-symbol contract valid | 1/3 | 0/3 |
| Training-symbol exact teacher set | 0/3 | 0/3 |
| Transfer contract valid | 0/2 | 1/2 |
| Transfer exact teacher set | 0/2 | 0/2 |

One transfer answer includes the right stackplot function plus an unrelated example.
Other cases often enumerate all candidates, violate max8 or continue counting.
Two adapter generations hit256tokens, after already-invalid enumerations; this is
not evidence that merely raising the output limit would yield a valid choice.
Candidate counts23/12/103and3/420; no input shortening. NLL across integer and
path targets is not directly comparable. This interface was not included in SFT;
negative results mix protocol distribution shift with choice difficulty, not a
clean proof of internal reasoning incapacity.

A separate exploratory (not preregistered) zero-inference sensitivity removes only
one complete outer JSON Markdown fence, symmetrically for both representations,
without changing the primary outputs/scores. Across5queries: base free exact0/5,
base IDs exact1/5; adapter free/IDs both exact0/5. Base had actually returned the
correct stackplot ID inside a fence. Strict format failures therefore hide a small
semantic signal; one exposed case does not establish a general gain.
Next proposed diagnostic: compare known-name->ID matching with issue->candidate
choice under frozen weights. No additional training or production promotion yet.


## Known-name lookup control (2026-10-26)

`scout-known-name-control-v1` freezes the same step24 weights and five symbol
catalogs. It supplies an exact path/name query chosen deterministically from the
catalog, independently of the repair labels. Original issue text remains as
background. This measures mechanical lookup under the new interface, not repair.

| Measure | Base | Adapter |
| --- | ---: | ---: |
| Exact known-name lookup | 0/5 | 0/5 |
| Valid candidate-ID object | 1/5 | 1/5 |
| Generations hitting limits | 0/5 | 0/5 |

Actual GPU execution completed in110.031s, ten local generations, no new training
or downloads. Fifteen focused tests passed. Symmetric single-complete-JSON-fence
removal was declared before dispatch and did not change lookup results.
Reports and raw outputs: `.keel/finetuning/scout-known-name-control-v1/`.
Comparison checks the same cohort, training receipt, checkpoint, generation
configuration and catalog mapping against the prior issue-selection reports.
The two tasks intentionally have different reference answers.

This rules out output truncation as an explanation for these lookup failures.
It does not isolate diagnosis ability: unseen instructions/ID encoding, catalog
presentation and interference from retained issue background remain possible.
Next proposed control simplifies catalog presentation and removes background
under fixed weights, before deciding on additional localization training data.
No production promotion or independent repair improvement is claimed.


## Lookup presentation controls (2026-10-26)

Actual frozen GPU study `scout-lookup-presentation-v1` completed20local
inferences in190.031s, with no training, downloads or hosted calls. It reuses
the prior five original-lookup results after identity checks.

| Presentation | Base exact lookup | Adapter exact lookup |
| --- | ---: | ---: |
| Original lookup (historical) | 0/5 | 0/5 |
| Original lookup, goal removed | 0/5 | 0/5 |
| Minimal instruction, explicit full candidate list | 0/5 | 0/5 |

All candidates, order, lookup queries, answers, output schema and checkpoint24
remain fixed. The flat condition bundles instruction simplification, metadata
removal and layout; it does not isolate layout as the cause. Eighteen related
regressions passed. Prompt hashes and tokens are recorded per inference.

One raw adapter output matters: on the three-candidate lookup it returns
`{"candidate_ids":["1"]}` with expected ID1. It found the correct identifier but
used a string where an integer was required. The strict score remains invalid;
this observation must not be described as a semantic misselection. Other outputs
contain wrong/extra candidates, so format repair alone would not solve the cohort.
The preregistered symmetric complete-JSON-fence sensitivity still has0/5exact.

Flat inputs are not uniformly shorter: the420candidate case grows from10987to
14042tokens, whereas the smallest case shrinks to261. Three flat generations
hit256output tokens while enumerating irrelevant candidates; the goal-removed
condition has no censoring. These results do not justify increasing budgets or
continuing prompt/epoch changes until one exposed case passes. Existing six SFT
controls have not established stable localization ability. Keep format recovery
and candidate choice as separate measurements before expanding reviewed data.

Artifacts: `.keel/finetuning/scout-lookup-presentation-v1/comparison.json`, frozen
`protocol.json`, original raw reports and `watchdog.json`. No production model
or original SFT targets were changed; no independent repair result is claimed.


## Error audit and the actual data bottleneck (2026-10-26)

`examples/audit_scout_lookup.py` replays hash-bound completed lookup reports,
reconstructs their catalog/query/answer from original exports and preserves all
primary scores. An opt-in secondary analysis handles one complete JSON fence and
canonical quoted decimal IDs. It never chooses using the reference answer,
removes extra predictions, guesses IDs or converts incomplete/prose answers.
This analysis is not enabled in production inference.

Actual zero-inference replay of30outputs (five source queries, three presentations,
two models), not30independent cases:

| Classification | Outputs |
| --- | ---: |
| Invalid protocol, not safely recovered | 14 |
| Wrong candidate after valid decoding | 5 |
| Multiple candidates for a one-candidate query | 7 |
| Incomplete generation | 3 |
| Correct after format-only recovery | 1 |

Strict exact remains0/30; secondary decoding is valid for9/30and exact for1/30.
This is posthoc sensitivity, not a newly learned capability. The audit finished
under its frozen watchdog in10.016s, with zero model calls or weight updates.
A later duplicate-JSON-key safety guard was checked against all30saved outputs;
all classifications match, and the implementation migration has its own receipt.
Thirty-one related unit tests passed.

`examples/prepare_scout_learning_queue.py` reconciles old reservations with actual
later exports and prior developer judgments. It creates metadata only and never
approves labels. The original28pending records contain20reserved-transfer rows;
the remaining eight training rows include six already-trained examples, one
excluded redundant Sphinx control and one held broad-symbol selection.
Consequently there is no fresh unassessed training row in that pool. This does
not make the held example permanently unusable; it still needs relevance evidence.
The historical four-used reservation is preserved, with an explicit six-actually-
used overlay. No evaluation answer is exported into training.

Artifacts: `.keel/finetuning/scout-error-audit-v1/summary.json` and
`.keel/finetuning/scout-learning-queue-v1/queue.json`.
The next data step needs task-diverse, source-bound original localization traces
outside the reserved evaluation tasks. Repeating the same six examples with more
epochs or alternate serializations does not create that diversity.


## Collecting additional source-bound Scout traces

Use `examples/collect_scout_trajectories.py` to prepare local pinned source and
then run the existing read-only Scout localization flow. It does not generate
patches, execute repository code, run the harness or approve training labels.
The plan excludes already-trained task IDs and reserved transfer/quarantine
repository families. Public solver inputs alone are read; private grading records
and reference patches are not opened.

Each request links immutable catalog source objects, a full visible-tree hash,
the public task/base commit and current ledger fact IDs. Responses are saved
before source-drift validation; invalid outputs and available incomplete completion
text/usage remain in the trajectory. Explicit `--resume-from` reuses completed
cases after plan/config/source/evidence checks, with historical costs labeled.
Partial or failed tasks are preserved, not silently replaced.

The first prepared pilot uses xarray4356 and scikit-learn14629: additional IDs for
this SFT dataset, but tasks already exposed in prior development runs. Existing
training examples and the Matplotlib transfer boundary remain unchanged.
The declared shared budget is300seconds,8model calls,120000tokens and40tools.
The launch uses the existing model config (currentlygpt-5.4-mini); its identity is
frozen. No new model calls have been made in the current tool environment because
its credential variable is absent. No new training samples are claimed yet.

Actual source preparation initially failed in Windows Git's shell-based local
fetch with signal-pipe access denial. The failed v1 is preserved. Shared native
Git archive export now prepares pinned source without that transport, checks the
commit comment, rejects unsafe members and binds archive/file hashes. Source-only
exports are not Git worktrees or official build environments. Actual v2 prepared
260xarray and1213scikit-learn files under its watchdog in20.015s, and completed
reuse was verified. Fifty-five relevant regression checks pass; mocked-teacher
unit tests are not live teacher evaluation.

Run the prepared pilot from a PowerShell session with the model key configured:

```powershell
& D:\keel\.keel\finetuning\scout-source-collection-v2\run.ps1
```

The script checks credentials before creating a collection attempt. Full raw
requests, source bindings, replies, tool ledger and costs remain under the output.
Inspect and source-review these records before any SFT export. This collector
is opt-in and is not automatically attached to every main Keel repair run.


The first live source-bound pilot completed on both planned tasks:5model calls,
20689reported tokens,43.25sAgent time and50.016swatchdog time. Actual source
bindings, immutable evidence and five post-call source-stability receipts verify.
Developer review approves the two unchanged xarray4356 file/symbol records for
future development export. Two scikit-learn file-page actions are excluded from
final-localization training; its symbol bundle is held because `_BaseChain.fit`
was selected in a `MultiOutputClassifier` issue. The teacher answer was not
trimmed or corrected to manufacture a usable sample. The public xarray issue
already includes a source hint, limiting what this control demonstrates.
See `scout-source-collection-v2/developer-review/review.json`. No new export or
training occurred: the current training dataset remains six examples. Next is a
CAS-bound export path; existing Git-based source exporters cannot assume these
source-only archive directories are Git worktrees.


## Source-bound development export v3

`examples/export_bound_scout_sft.py` now appends explicitly reviewed CAS-source
records to an immutable prior development export. It rechecks raw event identities,
source-binding and call-stability receipts, original goals, current selection
contracts, captured object hashes and AST declarations. Reserved repository groups,
page actions, duplicates and held teacher bundles remain excluded. Shared character
mask fixtures are reused; they do not substitute for a real tokenizer check.

Actual `scout-sft-dev-v3` has8examples across4tasks and3repositories. The first
six JSONL rows remain byte-for-byte identical; two unchanged xarray4356 file/symbol
responses are appended. The scikit-learn hold and Matplotlib transfer controls are
not admitted. The previous v2 dataset is preserved.

The offline pinned tokenizer check passed all eight complete conversations:
input lengths3072,1652,1860,673,3936,2288,2269,3281. Prompt/target offsets,
generation prefill, exact completion text and EOS boundaries agree. Existing
assets/environment were reused, without downloads, hosted calls or optimizer
updates. `scout-tokenizer-dev-v3-receipt` explicitly adopts the completed check;
`training_inputs` accepts this new dataset/receipt pair.

Evidence: `.keel/finetuning/scout-bound-export-v1/summary.json`,
`.keel/finetuning/scout-sft-dev-v3/export.json`, and
`.keel/finetuning/scout-tokenizer-dev-v3-check/results/check.json`.
Twenty-five related regressions passed. This prepares a tiny exposed development
training set; no new SFT run, production promotion or quality gain has occurred.


### Matched-update data comparison (2026-10-26)
The subsequent real GPU run `scout-data-comparison-v1` trained eight examples
for three epochs (24 updates), compared with the retained six-example/four-epoch
checkpoint. It completed in 290.031s including 20 local evaluation generations;
no hosted calls, downloads or production promotion occurred.

On the shared six controls, adapter contract validity fell from 4/6 to 3/6;
exact reviewed-teacher agreement stayed 2/6. On the same two exposed transfer
controls, contract validity rose from 0/2 to 1/2, but exact agreement stayed 0/2.
The legal transfer answer includes extra anchors. Added examples are training-fit
measurements, not transfer: contract1/2, exact0/2; one valid file subset need not
be semantically incorrect merely because it differs from the teacher bundle.

Equal updates do not equal equal exposure: input positions53924 versus57093,
and original examples repeat four versus three times. This single-seed tiny-data
comparison demonstrates no reliable quality gain. Retain the old checkpoint;
no checkpoint is selected automatically. Fourteen focused regressions passed.
Evidence: `.keel/finetuning/scout-data-comparison-v1/results/analysis/comparison.json`.
A proposed next diagnostic is aligned candidate-ID training/inference, preserving
logical targets; the prior ID experiment changed inference only.


### Aligned candidate-ID SFT result (2026-10-26)
The real `scout-id-aligned-comparison-v1` run completed in170.031s, with24
updates on the same eight examples and12local generations (base/adapter on
four symbol training queries and two exposed transfer queries). No hosted API
calls or production promotion. Original scoring rows are source/hash/mapping
validated, restored before filtering and numbered exactly once. Complete paired
coverage is checked;20focused regressions passed.

| Adapter metric | Free locations | Aligned ID training/inference |
|---|---:|---:|
| Symbol training contract |1/4|3/4|
| Symbol training exact teacher agreement |0/4|0/4|
| Exposed transfer contract |1/2|2/2|
| Exposed transfer exact teacher agreement |0/2|1/2|

The exact transfer response is candidate0 mapping to stackplot.py:16. The other
returns eight legal artist anchors with only one of four teacher anchors. One
training response still enumerates until the256token cap. File outputs were not
evaluated in this run. Input positions rose57093->65148;labelled positions fell
726->459. Cross-encoding NLL is deliberately omitted. Single seed, tiny exposed
cohort and bundled train/inference interface change prevent a general gain claim.
Retain both checkpoints and validate repeatability/encoding controls next.
Evidence: `.keel/finetuning/scout-id-aligned-comparison-v1/comparison.json`.


### Same-interface checkpoint control (2026-10-26)
`scout-id-interface-control-v1` reused the path-trained24update checkpoint on the
exact same ID prompts as the aligned model. It completed100.015s with12local
generations, no training or hosted calls. ID prompt hashes/token counts match;
base raw outputs match byte for byte. Existing completed reports remain intact.

| Adapter metric | Path-trained/path output | Path-trained/ID output | ID-trained/ID output |
|---|---:|---:|---:|
| Training symbol contract |1/4|0/4|3/4|
| Training symbol teacher exact |0/4|0/4|0/4|
| Exposed transfer contract |1/2|1/2|2/2|
| Exposed transfer teacher exact |0/2|0/2|1/2|

An inference-interface change alone did not reproduce the observed gain. This
supports a trained-checkpoint contribution on these queries, not a robust gain.
Correction: matching longest-first policies does not match actual sample order
when encoding changes lengths. Actual orders are recorded. The only exact
transfer target is candidate0, so position bias remains a live alternative.
A target-independent candidate permutation control is proposed before promotion.
Evidence: `.keel/finetuning/scout-id-interface-control-v1/comparison.json`.


### Candidate ID/order perturbation (2026-10-26)
`scout-id-permutation-v1` completed90.031s:8local generations,0training
updates/hosted calls.21focused regressions passed. Two target-independent controls
retain every candidate: reverse numeric IDs without moving rows; reverse the
catalog (with aligned metadata) and then renumber. Original reports are reused.

The3candidate stackplot case remains exact:original0, reversed IDs2, reversed
catalog2 all map to the same source anchor. Simple fixed-zero/first-entry choice
does not explain this case under these controls. The420candidate case remains
incorrect:reversed IDs produce the same14..21 numeric sequence now mapping to
different source anchors;reversed catalog causes enumeration to the256token cap.
All three presentations have1/2exact, representing the same two exposed queries,
not three independent successful tasks. No promotion or generalization claim.
This suggests investigating large-catalog selection with more approved cases;
it does not justify increasing the output cap or answer-dependent filtering.
Evidence: `.keel/finetuning/scout-id-permutation-v1/comparison.json`.


### Explicit lookup diagnostic on ID-trained checkpoint (2026-10-26)
`scout-id-lookup-diagnosis-v1` completed60.032s,12local generations,0training
updates/hosted calls.21related regressions passed. The same six catalogs are
queried by mechanically selected unique path/name, with issue background removed;
this is a separate, untrained control task, not new repair evaluation.

Adapter:6/6general-ID-protocol valid,1/6exact lookup; base:0/6exact. Only the
three-candidate query succeeds. Queries with12,23,103,184and420candidates fail;
all finish with EOS, so no output-cap increase is supported. The23candidate
response lists five legal IDs despite the exact-one instruction:general protocol
validity must not be confused with lookup compliance or correctness.

The result motivates controlled exact-lookup auxiliary training before increasing
repair complexity. It does not establish an intrinsic ability ceiling or a pure
catalog-size effect:lookup instruction is untrained and context/task changed.
Keep reserved catalogs evaluation-only, preserve original repair targets and
predeclare new training/evaluation splits. No production promotion.
Evidence: `.keel/finetuning/scout-id-lookup-diagnosis-v1/comparison.json`.


### Lookup auxiliary mixture (2026-10-26)
`scout-lookup-auxiliary-v1` preserves the eight original ID repair examples as a
byte-identical prefix and adds four mechanically labelled lookup conversations
from training catalogs only. Reserved transfer catalogs are excluded. Source,
mapping and reconstructed auxiliary targets are checked;22focused tests pass.
The real tokenizer verifies all12full conversations without truncation.

The real fresh-base run completed220.031s with12examples x2epochs=24updates,
versus the prior8examples x3epochs=24updates.24local generations,0hosted calls.

| Adapter exact agreement | Before | Auxiliary mix |
|---|---:|---:|
| Lookup on auxiliary training queries |0/4|1/4|
| Lookup on reserved exposed catalogs |1/2|1/2|
| Original symbol repair queries |0/4|0/4|
| Original exposed transfer repair queries |1/2|1/2|

No demonstrated transfer gain; no production promotion. This is one weak-fit
mixture run, not proof auxiliary learning is ineffective. Original repair repeats
fall3->2;input positions65148->60840,labelled459->384;order also changes. Next
proposed diagnostic is lookup-only fixed-budget fitting before more mixing.
Evidence: `.keel/finetuning/scout-lookup-auxiliary-v1/comparison.json`.


### Lookup-only fitting diagnostic (2026-10-26)
`scout-lookup-only-v1` trains a fresh same-base LoRA on four training-catalog
lookup conversations for6epochs=24updates. It completed200.016s with24local
generations and0hosted calls.22related regressions and real tokenizer checks pass.
Original repair datasets and reserved catalogs remain intact.

Lookup training exact rises to2/4 (prior mixture1/4, repair-only0/4), but reserved
lookup exact falls1/2->0/2. The two fitting successes have12/23candidates;other
training targets51and92generate1163(out of range)and102(legal but wrong).
Average target NLL0.10666 is not exact-ID accuracy. Original issue localization
remains0/4training and1/2transfer. No production promotion or repair gain.

This is fresh-base lookup-only training, not forgetting after continued repair
SFT. Input positions52224andlabel positions234 differ from the old24update run;
one seed/four fixed queries cannot establish a model ability ceiling. Proposed
next data work should diversify mechanical training queries/positions while
keeping reserved catalogs/queries excluded, rather than only repeating epochs.
Evidence: `.keel/finetuning/scout-lookup-only-v1/comparison.json`.


### Diverse lookup query/position data (2026-10-26)
`scout-lookup-diverse-v1` creates two hash-ordered unique path/name queries per
training catalog, excluding the original fixed query, with three complete-catalog
ID/order presentations. Eight semantic queries yield24rows across4catalogs;
reserved Matplotlib catalogs remain excluded.23focused tests and all24real
full-template tokenizer checks pass. Original repair data is retained.

The actual24rows x1epoch run completed210.032s,24updates/24local generations,
0hosted calls. Input positions52251versus52224for4fixedqueries x6epochs.
Frozen same-catalog excluded queries score1/4;the prior2/4was training fit,
so the difference is not an equivalent fit comparison. Reserved lookup recovers
0/2->1/2, matching the earlier ID repair baseline rather than setting a new best.
Original issue localization remains0/4and1/2;no production promotion.

These are exposed development controls, not an independent heldout result. The
next priority is broader fixed cross-catalog evaluation/data collection, before
more tuning against the same two migration queries. Keep historical weak and
strong baselines visible. Evidence:
`.keel/finetuning/scout-lookup-diverse-v1/comparison.json`.


### Broader fixed cohort and new collection preparation (2026-10-26)
`scout-cohort-expansion-v1` freezes21public development tasks/8repository groups:
10training-review,9evaluation-review,2quarantine. Existing trained repository
families and prior reservations stay intact;all historical exposure is retained.
Availability does not select membership. Local commit inventory found13ready and
8unavailable in listed clones;this is not a remote-source availability claim.

Full-source preparation first failed on Matplotlib symlinks. The strict archive
rule remains. `scout-cohort-sources-v2` retains15untrained/nonquarantine members:
5newtrainingexports,1verifiedScikitreuse,7unavailable,2export-blocked. Thus only
one full evaluation source is currently prepared, despite9fixed evaluation IDs.
Unavailable/blocked tasks receive no repair quality score.18related regressions
and real five-task source adoption pass;v1failure/costs are preserved.

`scout-source-collection-v3` is ready for xarray4075/4966,pytest6202/7982 and
Sphinx11510. It reuses exact sources and freezes public inputs/configuration.
The shared budget is600s/20model calls/240000tokens/80tools,outer660s. No new
teacher calls or labels exist yet:the tool process lacks the credential. Run in
a configured PowerShell:

```powershell
& D:\keel\.keel\finetuning\scout-source-collection-v3\run.ps1
```

Responses still require source and semantic review before SFT export. This is
broader data infrastructure, not a new model performance claim.


### Five-task collection review and15-example data version (2026-10-26)
The user live `scout-source-collection-v3` run collected all five tasks in80.031s:
10provider calls,27938tokens,17tools. Developer review verified570evidencefiles,
source bindings, original goals and all10nonpaged selections. Seven unchanged
responses were approved for exposed development training;three remain held.

Held:pytest6202symbolbundle includes a base empty reportinfo implementation that
the reproduced Function path overrides;Sphinx11510file/symbolbundles do not
establish the include-content reader path. Whole responses stay intact. No
reference labels were opened and no labels were repaired by pruning anchors.

`scout-sft-dev-v4` appends7approved examples to the byte-identical original8:
15examples,8taskIDs,3repositories. Four task IDs are newly approved;Sphinx11510
is not. Real offline full-template checks pass all15conversations, longest3936
tokens unchanged. `training_inputs` accepts the dataset/receipt;no training yet.
Pre-export review flags remain historical;the separate export receipt records
actual exported IDs. No runtime learning/generalization claim.
Evidence: `scout-source-collection-v3/developer-review/review.json`,
`scout-source-collection-v3/developer-review/export-receipt.json`, and
`scout-bound-export-v3/summary.json` under `.keel/finetuning`.


### Expanded15-example ID training at fixed update count (2026-10-26)
`scout-expanded-15-v1` completed260.032s. Generic `--max-updates` now permits
predeclared partial-final-epoch schedules, preserving full-epoch defaults. Both
models receive24updates:old8each3times,new15oncepluslongest9again.27focused
regressions pass. New ID data preserves old8rows;real token checks pass all15.

| Adapter exact teacher agreement | Old8 | Expanded15 |
|---|---:|---:|
| Common symbol queries |0/4|0/4|
| Added symbol training queries |not trained|0/3|
| Matplotlib issue controls |1/2|1/2|
| Matplotlib lookup controls |1/2|1/2|
| Reserved Scikit lookup |0/1|0/1|

The Scikit catalog has85candidates and is evaluation-only;the held repair teacher
is not used. A runtime guard prevents lookup-only exports being scored as repair
references.26local generations,0hosted calls,no promotion. File outputs were not
generated. Common partial recall improves in one pytest query via overselection;
this is not exact success or a new promotion rule. Input positions rise65148to
72371;labels459to446. New exposure1-2differs fromold3,so this does not prove new
data is ineffective. Next comparisons must separate exposure and compute budgets.
Evidence: `.keel/finetuning/scout-expanded-15-v1/comparison.json` and
`partial-agreement.json`.


### Equal exposure and actual-prefix control (2026-10-26)
`scout-expanded-15-exposure-v1` trains15examples x3epochs=45updates, matching
old8example3repeats but using more compute. It completes320.031s with24local
generations,0hosted calls. Environment/weights/reports reused;training is fresh
replay, not validated optimizer-state resume. No production promotion.

The replayed step24differs from the earlier24step run in all112adapter tensors
(max absolute0.000935607),despite matching configuration/order/seed. First-step
A weights match;B updates and gradient norms differ. The specific cause remains
unverified. A separate `scout-exposure-prefix24-v1` run scores this actual
trajectory's step24(140.032s,24generations,0updates) to avoid an invalid prefix claim.

Within the same trajectory24->45updates:common symbol exact0/4unchanged,new
symbol fit0/3unchanged,Matplotlib issue1/2unchanged,lookup1/2unchanged,Scikit
lookup0/1unchanged. Some outputs become censored/protocol-invalid. This does not
support a gain at45updates;it does not prove no higher-budget setting can work.
Priority next is bounded replay/determinism control or explicit repeatability
measurement, before more causal data/epoch claims. File outputs remain untested.
Evidence: `.keel/finetuning/scout-expanded-15-exposure-v1/paired-prefix-comparison.json`.


### Explicit reproducibility policy (2026-10-26)
`examples/run_scout_lora.py prepare|train --reproducibility strict` opts into
strict deterministic algorithms and pre-CUDA `CUBLAS_WORKSPACE_CONFIG=:4096:8`.
Strict mode seeds Python, NumPy and Torch with42. Default `legacy` preserves
historical setup; old absent policy fields normalize to legacy, not strict.
Recovery rejects a changed training policy; explicit `--reuse-preparation` may
reuse verified dependencies/weights while starting new training under a new
identity. Unknown policies, conflicting cuBLAS configuration and already
initialized CUDA fail explicitly; no silent backend fallback or truncation.
Training records effective execution policy; every new checkpoint includes
hash-bound `rng_state.pt` alongside optimizer state. This records state only:
no validated resume API or cross-device reproducibility guarantee is provided.
Evaluation verifies parent/training policy agreement and strict execution flags.
No localization improvement or model promotion follows from repeatability alone.

Validation: scout-strict-replay-v2 runs two independent15-step trials; every
step adapter/optimizer/loss and Python/NumPy/Torch CPU/CUDA RNG states match
exactly. Actual140.015s/30updates/0generations. Earlier v1 unseeded auxiliary
RNG mismatch is preserved. Total this development turn60updates; no quality
evaluation or adapter promotion.33 focused tests pass with Torch.


### Single-sample fit control (2026-10-26)
`scout-single-fit-v1` mechanically selects the shortest complete symbol input
(768tokens,sourceindex3). `export_subset` preserves raw teacher/catalog bytes
and verifies source lineage. Strict24update training yields fit1/1,validJSON/EOS,
NLL0.000450109; this is memorization. Two reserved exposed transfer queries
remain0/2exact. Total24updates/6localgenerations/0hostedcalls,no promotion.
Transfer task-provenance metadata failure is preserved; repaired scorer runs
only transfer in `scout-single-fit-transfer-v1`,reusing completed training/fit.
Single24repeats versus mixed3repeats does not isolate sample interference.
34 focused regressions passed with Torch. Evidence: single-fit comparison.json.


Single-fit prefix control: retained checkpoint3 outputs the entire0..11 list
and fails contract/exact;checkpoint24 outputs[9]and passes. Same training,
prompt and generation config verified;20.031s,0updates/2localgenerations.
Three exposures can fail even without other samples,so mixed-data interference
is not established. No learning-threshold or transfer claim. Evidence:
`.keel/finetuning/scout-single-fit-prefix3-v1/comparison.json`.


### Seven-symbol exposure control (2026-10-26)
All7originalsymbolrows,fullcatalogs/unchangedteachers,strict24epochs168updates.
Within one trajectory checkpoint21(each3exposures)versus168(each24):fit0/7->7/7,
contract5/7->7/7,censored2->0. Exposed reserved transfer1/2->1/2;larger case
still hits token cap and repeats164. TransferNLL worsens0.805801->2.124076.
This establishes multi-example memorization,not generalization or repair gain.
168updates/27newlocalgenerations/0hostedcalls;no adapterpromotion.
Initial blanket ID-cache ban stopped endpoint evaluation after completedtraining;
new guarded cache implementation validates interface/config/prompt identity,
reuses completed stages and runs missing adapter generations only.35focused
regressions passed. Evidence: scout-symbol-exposure-followup-v1/comparison.json.


### Invariance check on the fitted adapter (2026-10-26)
Retained168step7symboladapter:original7/7logicalexact,reverse_ids0/7,
reverse_catalog0/7. All modes retain7/7validcontractandEOS. Only1/7permode
repeats the complete old ID answer;others change but remain wrong. This shows
presentation fragility,not proof that all answers are fixed-number copies.
Teacher roundtrips,metadata,mappings,prompts/checkpoint and complete coverage
verified.110.031s/0updates/28newlocalgenerations/0hostedcalls;no promotion.
Next planned remedy is target-independent training permutations and separately
reserved unseen transformations,not more identical repetitions or answer fixes.
Evidence: scout-symbol-invariance-v1/comparison.json.


### Seeded permutation augmentation, matched-update pilot (2026-10-26)
Generic `shuffle_ids:SEED` and `shuffle_catalog:SEED` preserve logical anchors;
export_permutations validates source/targets and restores logical scoring rows.
7queries x4presentations x6epochs=168updates,24logical exposures;eachpresentation
only6repeats. Full28sampletokenizercheck passed. Evaluationseed prompts frozen
and verified absent from training; these remain exposed-task presentation tests.
Incumbent->augmented:original7/7->3/7,reverse IDs0/7->2/7,newshuffle0/7->1/7.
Transfer1/2unchanged;protocol/censor improves but no repair gain. No promotion.
Actual720.047s,168updates/60localgenerations/0hostedcalls;45focusedtests pass.
Next check the remaining trained presentations before attributing failures to
underexposure versus matching ability. Evidence: scout-permutation-train-v1/comparison.json.


### Full augmented-training fit audit (2026-10-26)
Retained adapter on all4trained presentations:3/7,6/7,4/7,3/7;16/28presentation
matches across7logicalqueries.3queries fit all4,6fit at leastone. Alladapter
outputsEOS. This rules out treating original3/7 as the entire trainingfit score.
Even the3fullyfitted queries score only2/3 on reverseIDs and1/3 on frozennew
catalogshuffle(post-hoc descriptive subgroup,not independent validation).
Both incomplete trainingfit and invariance gaps remain;moreepochs alone are
not established as the remedy.150.016s/0updates/42newlocalgenerations/0hostedcalls,
no modelpromotion. Evidence: scout-permutation-fit-audit-v1/comparison.json.
