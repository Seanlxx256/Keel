# Feedback ablation on development tasks

`examples/run_repair_comparison.py` prepares separate source copies for repair disabled (0) and enabled (at most 2 additional proposals). Both arms use localized-proposal, the same model configuration, 24,000-byte input cap, original task goal, acceptance commands, localization access and shared per-run budget. No task-specific patch is supplied. Only `verification_repair_attempts` differs. Case source restrictions and descriptions are inherited from existing curated tasks; this is not a blind localization benchmark.

The first cohort is Starlette 2526 and Flask-WTF 565. Both are previously observed development tasks. They are additional tasks relative to the successful HTTPX trial, but neither is held out. Four executions represent two tasks, not four independent samples. One run per arm is an initial diagnostic; provider randomness is not controlled by the execution-order seed. Success does not establish a general resolve-rate improvement.

Preparation freezes source inventories, acceptance case names, implementation hashes, configurations and reproduction receipts. Before any model request execution checks every arm. Existing started runs cannot be overwritten or resumed. Baseline failures must reproduce with exactly the expected case names; final success requires every case, scoped nonempty edits and runtime audit success. Reports retain failed/environment-error arms and costs. Compare matched tasks, reporting excluded environments separately rather than treating them as model failures or dropping them silently.

```powershell
python examples/run_repair_comparison.py --model-config .keel/model-openai.json --case 2526=.keel/upgradebench-reproduction/a5a65d40fa92407aa5ec9861910988d3 --case flask-wtf-565=.keel/upgradebench-reproduction/60f3db38a28b4bed9585ad4f22f1877d --output .keel/repair-comparisons/development-v1
python examples/run_repair_comparison.py --output .keel/repair-comparisons/development-v1 --execute
```

Normally each disabled arm uses three localization/proposal calls and each enabled arm uses three to five. Across this four-run cohort that is 12–16 normal calls; failures can stop earlier. The per-run configured global budget remains authoritative; each arm receives its own equal budget, not a new budget per retry. `results.json` checkpoints outcomes, failures, model/tool/token usage, verification rounds and elapsed time including baseline. Do not compare these numbers directly with the earlier HTTPX pipeline, which also selected installed dependency contracts and used different task evidence.

After this diagnostic, freeze the design and collect previously unseen tasks before further tuning. Keep benchmark readiness false until independent task/environment/acceptance criteria are actually met.
