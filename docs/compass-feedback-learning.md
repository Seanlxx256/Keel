# Compass feedback learning: current boundary and next experiment

Compass currently provides offline repository-held-out routing calibration in
`compass/calibration.py`. It chooses retrieval escalation thresholds using measured
development retrieval outcomes and separately reports holdout outcomes. It does not
update model weights, and its output explicitly does not claim online adaptation.
The current Keel SWE-bench batch does not call Compass retrieval.

A future feedback loop should distinguish retrieval failure from repair failure.
A failing test alone is not a relevance label: retrieved code may be correct while
the proposed edit is wrong, or verification infrastructure may have failed.

Proposed stages (not implemented by this document):

1. Within-task adaptation: feed observed errors into a new query, inspect additional
   symbols/callers, and retain rejected hypotheses without changing persistent policy.
2. Record candidate retrieval feedback with repository commit, query, retrieved symbol
   identities, evidence hashes, cost, and attribution status. A successful edit is a
   candidate signal rather than proof that every modified file should rank higher.
3. Review/validate feedback on development tasks, recalibrate offline, version the
   resulting policy, and compare quality and cost on separate tasks/repositories.
4. Keep policy frozen throughout evaluation; do not read reference patches or use
   evaluation outcomes to update the policy and then call the same runs held-out.

First establish the Keel recovery baseline on the next fixed batch. Compass integration
should be a separate comparison with the same task set, budgets and acceptance rules.
No automatic persistent learning or fine-tuning claim is justified yet.
