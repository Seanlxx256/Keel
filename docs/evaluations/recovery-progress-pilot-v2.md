# Recovery progress feedback: completed development pair

Source: `.keel/repair-ablation/progress-v2/comparison.json`.
Plan SHA256: `3ffb2516eb8eb15cd4dc6f21f4d1334ed288a9a324f12c858f6da3708dd6de26`.
Frozen plan/input/implementation checks passed. Both trial, final-grading and
trace receipts matched; official report hashes were checked independently.
No rerun was launched for this review.

| Arm | Runtime / official result | Calls | Tokens | Agent seconds | Intermediate verifications | Feedback dispatches |
|---|---|---:|---:|---:|---:|---:|
| Baseline | failed / unresolved | 11 | 64,518 | 320.703 | 1 | 0 |
| Progress feedback | failed / unresolved | 11 | 63,087 | 322.797 | 1 | 1 |

Both arms had identical 12-call / 80,000-token / 900-second Agent ceilings. Both
stopped in Scout because the next request's estimated input/output reserve could
not fit the remaining token budget; neither consumed exactly 80,000 billed tokens.
Preparation and final grading are outside Agent totals. Combined reported Agent
cost: 127,605 tokens, 22 calls, 643.500 seconds.

Both final official reports have FAIL_TO_PASS 1 passed, PASS_TO_PASS 173 passed /
1 failed. The remaining failure is test_invalid_float_cards2. Each arm produced
one tested candidate; equal preservation-first ranks retained/restored the saved
seed. This is not successful runtime recovery or a repair-quality gain.

## Exposure versus effect

The treatment dispatched one later Critic request carrying prior-round progress
context. Its first inventory reported [1,0] -> [1,0] (tied), actual source facts
and matching new verifier receipts. Its second question had no later observations
or reverification before termination. The later Critic again requested inspection
of the formatting/verification path. Inventory and handoff worked, but an improved
diagnosis or effective next repair was not established.

The 1,431-token difference is descriptive, not demonstrated savings. One exposed
task, fixed order and one sample per arm cannot establish generalized efficacy.
Keep feedback off by default. Do not launch another full rerun just because the
mechanism was exercised.

## More specific offline observations

Scout consumed 50,890 / 48,902 tokens (approximately 79% / 78%); Critic consumed
7,610 / 7,588; Implementer 6,018 / 6,597. Both trajectories also selected a
protected test path for writing and required correction. These are observations,
not proof that localization alone caused failed repair.

The test was not wholly missing: ledger fact 14 in both arms contains
test_header.py lines 2000..2055, including the failing test. Treatment Scout's
fact 16 summary describes the test as expecting an invalid lowercase-exponent
string to remain during reserialization. The actual displayed test first writes
a valid file, then manually changes the exponent to make it invalid, and finally
checks warnings. The summary fails to distinguish these phases. This supports
a contract-interpretation/handoff concern beyond locating the file. It does not
prove the exact runtime causal defect or full test-body delivery to later roles.
Do not insert a task-specific correction into production runtime from this review.

## Next falsifiable work

Pause full Astropy reruns. Offline inspect actual role handoff and the next-request
reserve calculation. Separate redundant localization cost, missing evidence and
incorrect test-phase interpretation. A later small evaluation can test recognizing
setup versus intentionally invalid input and choosing a phase-specific check,
without supplying a repair answer. Avoid another mandatory reflection layer.

Trial hashes: baseline `686d24d903ed5e4691f20bed3b0c98a1fe5dcc6022c68010037e9dc7312bfa1d`;
progress `76eef7b24c664cd0e801b5cc6a921cfbb5e02cd1fae75b3bcdfadbd7deac8f06`.
