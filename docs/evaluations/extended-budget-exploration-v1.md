# Extended-budget exploration: stopped before implementation

Source: `.keel/swebench/astropy-14508-extended-v1/trial.json`.
Trial SHA256: `bc8f23a6d2cae53bdf236111dbc451b42423d79860017da94652b2327b77739f`.

The user requested one larger-budget mini attempt, retaining source, acceptance
and progress feedback. It completed unresolved: 7 calls, 43,040 tokens, 4 tool
calls, 69.938 Agent seconds; total trial elapsed was 257.390 seconds, including
additional preparation/final grading. The 60-call / 400,000-token / 3,600-second
allowance was not exhausted. No second attempt was launched for review.

The actual stop was repeated invalid localization, not exhausted global budget or
the twelve-action allowance. Ledger facts 11, 13 and 15 each selected the same
protected test path as a writable source target; the third selection added another
source file but still contained the rejected test. Two correction observations
explicitly identified that path and its read-only status. The repeat guard then
stopped before a further action was recorded. The broad runtime category
budget_exhausted/message covers repeated failure too and must not be interpreted
as evidence of reaching a numeric global limit.

Scout's preceding exploration read the test file through read_file, receiving a
prefix preview; its own summary acknowledged not reaching the failing test body.
It nevertheless carried both implementation and test paths as candidates. The
later writable selection repeatedly included the latter. No implementation was
produced, no intermediate verification ran, and run/changes.patch is empty.
Final independent grading of the inherited seed has FAIL_TO_PASS 1 passed,
PASS_TO_PASS 173 passed / 1 failed. The official report hash matched grading
metadata. This is not a newly tested failed repair candidate or a successful
continuation, and the PowerShell nonzero-exit exception is the launcher's intended
no-retry behavior rather than the original fault.

## Generalizable observation

This repeats an already documented file-selection failure class: readable test
evidence and writable repair targets are confused. Current host validation does
protect tests, but error prose/retrying did not correct model behavior here.
selection_request constrains item IDs in paged catalogs but the nonpaged schema
currently permits arbitrary strings. That is an interface weakness, not proof
that adding an enum alone will solve it: copying a large catalog into the schema
can increase input size and paging cost, and JSON-object providers do not enforce
every schema at the server. Host validation must remain authoritative.

Next work should separate readable evidence navigation from writable selection
and evaluate constrained catalog choices with existing context-budget/paging
tests. Do not silently filter invalid paths, auto-select the surviving source,
disable test protection or loosen the repeat guard just to get past this run.
No task-specific repair or new production selection change was made in this review.
Any further paid attempt needs a fresh identity; the single authorized run ended.
