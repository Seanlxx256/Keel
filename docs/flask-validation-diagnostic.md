# One-run validation diagnostic

After adding bounded proposal validation feedback, prepare only the enabled Flask-WTF arm, not another four-run cohort. This starts from the original base with the unchanged four curated acceptance cases. No known repair snippets are inserted.

The check is whether a rejected proposal can be corrected against unchanged evidence, followed by independent acceptance and bounded verification repair if needed. A first-proposal pass is a task pass but does not exercise validation recovery. Inspect `proposal_validation_failed`, `Proposal rejected before writes` facts and verification attempts to distinguish these outcomes. Syntax correction does not establish dependency API correctness.

```powershell
python examples/run_repair_comparison.py --model-config .keel/model-openai.json --case flask-wtf-565=.keel/upgradebench-reproduction/60f3db38a28b4bed9585ad4f22f1877d --repair-arms 2 --output .keel/repair-comparisons/flask-validation-v1
python examples/run_repair_comparison.py --output .keel/repair-comparisons/flask-validation-v1 --execute
```

Preparation makes no provider requests. One run normally makes 3–10 model calls, including possible localization refinement, one invalid-proposal retry per proposal, and at most two verification repairs with evidence selection. The existing total budget remains the actual bound. This is a single-arm development diagnostic: paired success rates will be null and the missing disabled arm explicitly reported. Do not use it as a new paired comparison or benchmark sample. Retain the failure if it fails; this diagnostic is not authorization to keep rerunning until a pass.
