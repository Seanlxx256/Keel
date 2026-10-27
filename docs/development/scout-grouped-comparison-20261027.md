# Post-restart resource validation and amended grouped comparison

The operator applied E-drive pagefile32768/49152MB and restarted Windows.
Read-only checks confirmed commit limit47.73GiB,available commit32.86GiB and
available physical5.61GiB. D has5.80GiBfree,E49.14GiB. No assistant OS change.

The first exact-outer-path smoke stopped at its60-second environment stage,
before training. Explicit phase timing then measured successful startup64.9s:
Torch4.6s, CUDA check0.1s, transformers model class import53.9s, peft3.0s,
inventory3.3s. Cold cache/driver/antivirus contributions were not isolated.
The shared setup now accepts explicit environment_timeout (legacy default60),
records it, and clamps it to the existing total deadline; CLI prints phase times.

The new frozen v2 smoke used180seconds for environment checking and the same
outer watchdog path as operator runs. Both grouped policies completed5updates,
saved checkpoints and fresh-process7rowevaluations. Total240.047s,10updates,
14scoreforwards,0hostedcalls/downloads. Minimum available host commit18.14GiB;
GPU peaks2.067/1.850GiB. Both one-small-training evaluations scored0/7exact.
This validates resource/interface feasibility, not localization improvement or
causality from pagefile alone.50relatedregressionspassed2.944s.

Evidence: `.keel/finetuning/scout-grouped-outer-smoke-v1` (failure) and `v2`
(pass, host-memory trace, environment phase log, raw checkpoints/scores).

## Prepared full comparison, not dispatched

`.keel/finetuning/scout-grouped-comparison-v1/run.ps1` runs an amended study:

| Cell | Training |
|---|---|
| numbered_end | Reuse original completed168steps/final checkpoint |
| id_free_end | Reuse original completed168steps/final checkpoint |
| numbered_after_grouped | Fresh168steps,6epochs on28presentations |
| id_free_after_grouped | Fresh168steps,6epochs on28presentations |

Old ungrouped failures are preserved. Grouping changes serialization to avoid
repeating each file path for every symbol; all candidates and full-catalog
readout coverage remain. Runtime lifetime handling and machine state differ
from old controls; timing is not a pure architectural comparison.

Before dispatch196actualmodel-inputhashes were frozen across7exposedqueries,
four training displays, a new ID shuffle and two new catalog shuffles. Fresh
catalog inputs are absent from training. ID-free ID-only permutations duplicate
training inputs by design and are not novel generalization. No new task labels,
independent repositories, threshold fitting or production promotion.

56existing control-fit forwards are reused only after actual token-input matching
and final checkpoint/receipt verification. Planned new work:336updates and140
scoreforwards. Archived control intermediates are not needed: finalstep168 stays
in place. Shared budget1800seconds; outer watchdog1860seconds includes reserve.
Environment cap180seconds/traincap1200seconds remain bounded by shared time.
Partial completed work remains available if the budget proves insufficient.

Automatic analysis validates finalcheckpoint168, report/training identities,
actual input hashes, all samples, canonical candidate sets, teacher membership,
and fixed0.5/max8policy. It reports training-fit and fresh-catalog exact counts
separately and never selects or promotes a model. Final fresh catalogs contain
14presentations of7knownqueries, not14independent tasks.

## Completed run and independently verified results

Operator run completed1590.437seconds, within the shared30-minute budget. New
work:336optimizerupdates and140scoreforwards; reused336controlupdates and56fit
forwards. Frozen runtime/input/report hashes and all four finalstep168
checkpoints independently verified after completion. Minimum available host
commit15.33GiB, no memory-telemetry errors. D now has3.51GiBfree. No model
promotion, provider call, reference-label change or threshold fit occurred.

| Representation | Training exact /28 | New catalog exact /14 | Training token positions | Training seconds |
|---|---:|---:|---:|---:|
| Numbered, candidate end | 12 | 3 | 384384 | 389.875 (reused) |
| ID-free, candidate end | 23 | 4 | 327288 | 313.421 (reused) |
| Numbered, grouped after catalog | 8 | 1 | 579120 | 659.062 |
| ID-free, grouped after catalog | 9 | 4 | 465432 | 470.562 |

New catalog panel counts respectively:0+3,2+2,0+1,2+2. These seeds differ from
the prior ungrouped study: do not directly compare old1/14vsnew3/14 as a model
change. Identical checkpoint under different presentations can yield different
counts. All queries remain exposed development controls. Equal168updates is
not equal token/compute/order; timing also spans runtime/machine migration.

The amended full-context-readout variants did not improve final fresh-catalog
selection in this study. ID-free candidate-end is the stronger development
candidate by fit and ranking, but its4/14exact is still weak. The one-success
advantage over numbered3/14 is too small and correlated to prove independent
generalization or official repair gains.

### Zero-inference error decomposition

`error-decomposition-v1.json` binds `comparison.json` and uses already recorded
scores. Strict perfect ranking means min positive teacher-member score exceeds
max nonmember score. Nonmembers are teacher-set negatives, not certified
semantically irrelevant definitions. False positives/negatives below are actual
capped final-set errors. No oracle count or threshold adjustment was used.

| Representation | Training perfect ranking /28 | Fresh perfect ranking /14 | Fresh mean teacher AP | Fresh FP / FN |
|---|---:|---:|---:|---:|
| Numbered, end | 17 | 4 | .6904 | 53 /9 |
| ID-free, end | 28 | 9 | .8612 | 5 /15 |
| Numbered, grouped after | 21 | 7 | .6990 | 57 /8 |
| ID-free, grouped after | 20 | 4 | .6792 | 4 /25 |

ID-free candidate-end has5fresh presentations with perfect ordering but a wrong
selected set. This motivates separating ranking from threshold/count selection;
it does not establish that one global calibrated threshold will improve new
presentations. Prior legacy-head calibration failed aggregate generalization.
Any new calibration must use training rows only, freeze fresh evaluation inputs,
retain this study as exposed evidence and avoid tuning on these14outcomes.
Independent task/repository validation remains required before promotion.
