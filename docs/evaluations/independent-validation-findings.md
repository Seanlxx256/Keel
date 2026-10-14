# Independent-issue validation findings

Source run: `.keel/swe-independent/e2837c5dfd3142e2807661fb6e9e7cef/`.
The user execution completed in approximately 509 seconds. Requests 1142 was
ineligible in all four modes because its index was incomplete. Seaborn 3187
completed all four modes. Overall `all_passed=false` correctly retains the partial
failure; this is not a successful two-instance evaluation.

## Requests diagnosis

The sole index diagnostic is in
`requests/packages/urllib3/contrib/ntlmpool.py`, line 38. Its historical docstring
contains the literal `DOMAIN\username`. `PythonParser.parse` first calls Python
3 `ast.parse`, which rejects the incomplete `\u` escape. Tree-sitter availability
does not bypass this AST gate. Model exploration itself completed, but its
results remain excluded by index-completeness policy. No dependency or token
budget failure explains this result. The snapshot must remain unchanged while
historical-source parsing compatibility is addressed explicitly.

## Seaborn budget comparison

Saved candidates were replayed without model calls at
`checked-budget-analysis/` within the source artifact directory. All four
Requests configurations were excluded, leaving one independent task.

| Mode/configuration | Line recall | Line precision | Emitted lines |
| --- | --- | --- | --- |
| T1 100/32 replay | 3.77% | 100% | 100 |
| T1 300/32 replay | 5.54% | 49% | 300 |
| T1 300/64 live and replay | 7.27% | 64.33% | 300 |
| T2 300/64 live and replay | 1.43% | 100% | 38 |

T2 used two model calls and about 21 seconds; T1 used no model calls and about
6.7 seconds. These timings include uncontrolled caches and residency effects.
Increasing total budget does not expand T2's fixed 38-line selection. Its perfect
precision describes the selected lines, not coverage of all relevant code.

The wrapper skipped automatic replay because the source batch was incomplete.
The separate checked replay intentionally retained only eligible configurations;
it preserves exclusions and source hashes without modifying the original run.

The candidate 300/64 setting shows a recall improvement on the newly examined
Seaborn issue, with a precision tradeoff. One eligible instance does not establish
generalization. Requests parsing compatibility must be resolved before claiming
the planned two-instance validation is complete. Official evaluator parity is
unverified.
