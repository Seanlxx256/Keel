# Eligible-only diagnostic after insufficient cohort coverage

Collection `470726aefcd8496e816ad6b2452de4ea` completed all four repositories. Of 12 collected candidates, only Sphinx 13786 (`Support Docutils 0.22`) passed the fixed metadata screen. Ten rows lacked dependency/version evidence and four exceeded the source-count constraint (reasons overlap). The original policy requires two repositories, so its status correctly remains insufficient_candidates and selected remains empty.

Do not lower the old threshold or silently replace selected IDs. The separate `--eligible-only` review mode accepts complete insufficient cohorts with nonempty eligible screened rows, retains original shortlist hashes and explicitly labels the review diagnostic. It neither changes the collection nor counts the row as an independent executable task. This cohort currently has exactly one eligible row, avoiding an arbitrary choice among multiple rows.

Prepared review: `.keel/candidate-review/cab7410dd1614bd588da056783d233b5`. Next command fetches pinned source snapshots and performs curator AST review only; no Docker and no paid model calls:

```powershell
python examples/review_independent_candidates.py --collection .keel/independent-candidates/470726aefcd8496e816ad6b2452de4ea --eligible-only --execute
```

After source review, a valid old/new dependency transition still needs reproduction. Metadata eligibility, AST change and a compatibility title do not by themselves prove a failing task. Two new review-mode tests and eight existing candidate selector/review tests passed. Source snapshot fetching has not yet been claimed successful.
