# Three-repository paired development baseline

The user run at `.keel/swe-public/60684397b18344489bf89fcdadae590c/`
finished on 2026-10-14 after approximately 1,073 seconds. It attempted 72 runs:
three development instances, two rankings, four modes, and three repetitions.
Sixty runs completed; twelve Requests T2/adaptive runs failed. The overall exit
code of 1 correctly preserves this partial failure. Flask and Seaborn completed.
Compact results and the source result hash are retained in
[the JSON record](swe-three-repository-baseline.json).

| Instance | RRF T1 line recall | Code-aware T1 line recall | T2/adaptive execution |
| --- | --- | --- | --- |
| Flask 5014 | 0 | 0.03195 | Completed |
| Requests 1724 | 0 | 0 | Failed token preflight |
| Seaborn 3069 | 0.01637 | 0.01675 | Completed |

For Requests, all failed model modes reported `Insufficient token budget for next
model call` after one model call using 686 reported tokens. Its first response
requested an additional search. The resulting observation included the original
issue again, and full action schemas accumulated as user messages. The next
call's conservative byte-based input estimate exceeded the remaining 30,000-token
budget. This was an input preflight failure, not 30,000 actual consumed tokens,
a missing dependency, or a download failure.

## Prompt construction correction

Per-turn schema instructions are no longer stored in conversation history.
Structured adapters receive the schema once through their response-format field;
plain adapters receive one current schema in the prompt. Preflight still includes
schema bytes, uses the same conservative upper bound, and enforces the original
token/call/time limits. Query observations retain the new terms and evidence,
without duplicating the full original issue. The original issue remains in the
conversation and every hybrid query. Invalid observations retain the error and
visible IDs without another schema copy. Preflight events now record the input
upper bound, output allowance, and consumed tokens for diagnosis.

A diagnostic replay of Requests' original first query action with a scripted
second final action passed the unchanged budget: first input bound 15,707 bytes,
second 28,722 bytes, with 686 consumed tokens before the second call. This checks
multi-turn construction; it is not a live-model quality result.

The live one-repetition follow-up at
`.keel/swe-public/a8f16d6884024b5697c68b4eaff87889/` completed all eight policy/mode
runs with the original budgets. Its model modes returned valid final selections
in one call, so it does not itself demonstrate multi-step exploration.

An initial three-repetition follow-up encountered a Git `ls-files` exit 128 while
regression tests were running. That attempt remains failed; it is not counted as
a successful prompt-fix validation.

The serial three-repetition follow-up at
`.keel/swe-public/670c7cdc47d34238a2f823d93e40118c/` completed 22 of 24 runs.
No token-preflight failures occurred. RRF T1 and adaptive in repetition 0 failed
the Git base-commit check; those records remain excluded, and the run returned
exit 1. Code-aware completed all 12 runs. This is evidence that the original
prompt-budget failure was avoided, but is not a fully passing repeated batch.
Its mixed execution status must not be merged into the original baseline as
though all configurations had been rerun successfully.

These are three development tasks, not a held-out evaluation. Repetitions share
caches, and any excluded mode has a different task denominator. Quality results
from different prompt implementations must remain separate. Official evaluator
parity and leaderboard performance remain unverified.
