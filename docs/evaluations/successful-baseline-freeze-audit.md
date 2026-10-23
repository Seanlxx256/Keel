# Successful baseline freeze audit, 2026-10-23

User challenges whether acceptedv4 was truly frozen before token-policy work.

Preserved: v4 model/probe configs, launch arguments, full transcript, ledger,
source patch/workspace, runtime result, official grading artifacts and185runtime
implementation SHA256 entries. These identify evidence and implementation content.
Missing: a complete archived copy/isolated checkout of those185runtime files at
their v4 hashes. Hashes cannot reconstruct missing bytes; current Git HEAD is
fadab93, not a verified completev4 source snapshot. Do not claim exact runtime
reproducibility or silently replace a snapshot with current files.

V4 to v5 changed runtime inventory entries:

- examples/run_swebench_task.py
- keel/models.py
- keel/proposals.py
- keel/runtime.py
- pyproject.toml
- added keel/context_budget.py

Token policy also changed from48ksoft/52.8khard to explicit model/input/safety/
byte policy. Hencev5 was not an unchanged repeat. Afterv5 another change to
keel/campaign_reporting.py preserves future completion-error diagnostics.

Direct transcript comparison: first Critic message arguments and schema exactly
equal in v4/v5; both complete_json,max_output1024. Model config and probe config
bytes equal. V4 passed; v5 first completion failed. V5 never reached proposal
context logic. This excludes a changed first prompt as explanation, but does not
establish the actual provider failure cause because finish reason was not stored.
Do not infer new-policy regression or guaranteed model stochasticity from this.

Correction: preserve old artifacts and label future policy runs as changed
conditions. Before another experiment freeze exact current runtime bytes plus
configs/inputs/environment identities in an isolated snapshot, verify hashes on
execution, retain baseline separately, and run one-factor checks. Existing user
authorization does not authorize Git commits, resets or discarding changes.
