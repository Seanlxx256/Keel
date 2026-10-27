# Frozen representation comparison: partial results and resource failure

Four policies, unchanged reviewed data (28 presentations of 7 exposed queries),
six epochs/168 updates each, fixed threshold 0.5/max8, strict seed42 and shared
rank4 q/v LoRA. Runtime snapshot and 196 actual evaluation token-input hashes
were frozen before training. Fresh catalog permutations are not independent
tasks. ID-only permutation of an ID-free prompt is training-identical by design.

Evidence: `.keel/finetuning/scout-representation-comparison-v1/`.

## Completed half

`partial-verified-comparison.json` validates the completed two cells against
frozen actual input hashes, checkpoint receipt hashes, candidate membership,
policy and complete sample coverage. No model was selected or promoted.

| Metric | Numbered / candidate-end | ID-free / candidate-end |
|---|---:|---:|
| Training presentations exact | 12/28 | 23/28 |
| Original display exact | 3/7 | 6/7 |
| New ID shuffle exact | 2/7 | 6/7 (input already seen) |
| New catalog shuffle 1 exact | 1/7 | 2/7 |
| New catalog shuffle 2 exact | 0/7 | 3/7 |
| Training seconds | 389.9 | 313.4 |

Both cells completed 168 updates and 49 scoring forwards. This is preliminary
evidence favoring the ID-free interface in these exposed queries; differing
instruction text, token counts and longest-first order are part of the treatment.
It is not a complete factorial/visibility result, independent repair improvement,
or an argument for tuning these evaluation outputs.

## Failed third cell

`numbered_after` failed on its first 8085-token sample at AdamW foreach sqrt,
with stderr `fatal : Memory allocation failure` and CUDA unknown error. Zero
completed steps/checkpoints were saved for that cell; partial optimizer effects
before the asynchronous error are not certified. GPU allocated peak was about
2.273 GiB. The fourth cell never started. Original watchdog ended unresolved
after 1100.079 seconds; it did not hit its time limit.

PowerShell startup also failed with HRESULT 0x800705AF. An after-failure resource
query showed normal GPU availability. A separate synchronous-CUDA single-step
diagnostic using the same frozen implementation and training configuration
passed, with host available commit dropping to approximately 0.152 GiB and
available physical memory to 0.913 GiB during half-second sampling. This supports
system resource pressure as a concern; it does not prove the exact allocation
mechanism or certify that a long unchanged retry would be stable.

The conversation's model-capacity message did not stop either of the first two
local training cells. The later CUDA/allocation failure is a distinct event.

## Recovery prepared, not dispatched

`continuation-v1/run.ps1` reuses hash-bound completed first-two-cell reports and
restarts only the missing third/fourth cells from base under the original data,
weights, seed, encoder, threshold and evaluation manifest. Failed output is
preserved separately; this is not checkpoint resume. The new shared deadline is
4200 seconds with a 4260-second outer watchdog; preparation's train stage now
accepts an explicit positive finite timeout (legacy default600), bounded by the
existing total deadline. The continuation retains the frozen1200-second train
budget per cell. No automatic long retry was dispatched under near-exhausted
host commit.

Release host memory/commit pressure before dispatch; do not delete checkpoints,
truncate catalogs or change optimizer numerics merely to hide the failure.
Monitor host commit through long GPU work, because a successful one-step smoke
does not certify ongoing machine availability. Resource samples and diagnostic
results remain under `optimizer-diagnostic-v1` and the host-memory JSON files.

48 related regressions passed after the failed run (3.506 seconds). Completed
study work: 336 saved optimizer steps and98 scoring forwards, plus one separate
completed diagnostic update; the failed update is retained as an attempted,
uncertified step. Zero hosted calls/downloads. Full four-cell comparison remains
unfinished.

## Continuation-v1 failure and forward lifetime change

The user-dispatched continuation stopped unresolved after50.015seconds, before
any completed optimizer step. This time CUDA explicitly reported out of memory
at gradient clipping on the first8085-token input; the asynchronous error means
that frame alone does not certify the original failing allocation. Peak tensor
allocation again was2440699904bytes. This was not the4260-second deadline.
Previous advice to release host memory was insufficient to resolve it.

The shared trainer now drops forward output/logit/loss references after backward,
keeps the scalar loss for reporting, and empties inactive CUDA cache before
gradient clipping/AdamW. No input, precision, parameterization, optimizer or
selection policy changed. Clip/optimizer phases and post-backward allocated/
reserved bytes are persisted so a later failure is easier to locate.

Two fresh longest-input one-step trials passed (synchronous CUDA and ordinary
asynchronous CUDA), total91.953seconds. Actual adapter tensors, score-head
tensors, AdamW states, all recorded RNG states and loss were exactly equal to
the original implementation's successful synchronous diagnostic. This is a
single-input single-step equivalence result, not full-run bitwise certification.
Post-backward allocated/reserved bytes were1263885312/1304428544. Evidence:
`.keel/finetuning/scout-optimizer-headroom-v1/state-comparison.json` and raw trials.

Host commit still fell extremely low: sampled minima16224256bytes and2772992bytes
in the two trials. Thus the passing smoke does not certify stable long training
under the current competing machine load. No long automatic retry was launched.
48 focused regressions passed3.110seconds. This turn added2completed diagnostic
updates,0scoringforwards/hostedcalls/downloads; both full-run failures remain.

`continuation-v2/run.ps1` is prepared, not dispatched. Its frozen runtime differs
from the original study only in `keel/scout_lora.py`; migration binds the exact
equivalence proof and completed first-two-cell artifacts. Only missing cells
restart from base, with unchanged data/seed/epochs/threshold/evaluation inputs.
Timing has an explicit runtime migration confound. A lightweight host-memory
sampler persists during execution; telemetry errors do not mask required study
results. Release competing host commit pressure before running it. Do not rerun
continuation-v1 or overwrite existing failed/completed outputs.

## Continuation-v2: backward fails before cleanup; measured host exhaustion

The user-dispatched v2 ended unresolved40.031seconds, with0savedsteps. It emitted
fatalMemoryallocationfailure/CUDAunknownerror inside backward on the same8085
token sample, before the new cleanup could execute. Peak tensor allocation was
1919199232bytes. The sampled available host commit fell from7.36GiB to7516160
bytes; minimum physical availability was about0.264GiB. Therefore forward cleanup
alone did not resolve the peak. Do not characterize this as timeout or claim the
previous two passing single-step controls certified full-run feasibility.

Added two explicitly new representations, numbered_after_grouped and
id_free_after_grouped: retain the complete original catalog, then group readouts
by file so each path is written once per file rather than per symbol. Every
candidate identity and mapping remains, and all readout positions follow the
complete catalog. The original frozen modes and outputs remain unchanged.

Real offline tokenizer checks across28trainingpresentations preserve all
locations/IDs; longest inputs8085->6565 and6463->4943. Two optimizer steps per new
mode passed under frozen local diagnostic implementation,88.656seconds total,
fourupdates/0scoringforwards/hostedcalls/downloads. GPU peaks2.067/1.850GiB;
minimum available host commit0.275/0.538GiB. These are new-input resource smokes,
not numerical equivalence to the old serialized prompts, quality gains or proof
under the complete outer watchdog. No new full continuation was dispatched.
Evidence: scout-grouped-readout-preflight-v1 and scout-grouped-readout-smoke-v1.
49relatedregressionspassed3.207seconds. Initial new test incorrectly expected
definition_bytes in readouts; corrected it to compare the intended path/symbol
fields while the complete original catalog still retains its metadata.

Read-only registry inspection reports E:\pagefile.sys0 0 (automatic management).
Actual shutil.disk_usage readings: C4.8,D3.6,E59.5,F49.3GiB free. The PowerShell
provider returned unavailable Free values that rounded to0; these are not disk
full evidence. No pagefile, applications or OS settings were changed.

Microsoft documents that automatic pagefile growth latency can cause allocation
failures: https://learn.microsoft.com/en-us/troubleshoot/windows-client/performance/slow-page-file-growth-memory-allocation-errors
That specific mechanism is unproven here; near-exhausted available commit is
directly measured. An operator can preallocate more E-drive pagefile capacity
(e.g. initial32768MB/max49152MB based on this machine's observed demand and disk
space) and restart before further long runs. These are machine-specific planning
values, not new model/context hard limits or guaranteed sufficient capacities.
Release competing workload too; retain all failed and completed experiment data.
