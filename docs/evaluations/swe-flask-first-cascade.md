# First public SWE-Explore cascade attempt

On 2026-10-14, the cached public-data runner evaluated `pallets__flask-5014`
at base commit `7ee9ceb71e868944a46e1ff00b506772a53a4f1d`.
Artifacts: `.keel/swe-public/d9ede778606c4d37935e0807563edbdd`.

The run used one instance, one repetition, a 100-line context budget,
tree-sitter, SQLite vectors, `keel-embed` and `keel-chat` through local Ollama.
The embedding runtime used `num_batch=32`. Model inventory and data provenance
are preserved in the artifact directory. Dataset revisions were
`bdb0ae45d7c337d9e1dc3ebfe2a0af6bc7c1fbd9` (SWE-Explore) and
`c104f840cc67f8b6eec6f759ebc8b2693d585d4a` (Verified metadata).

The original attempt crashed in native tree-sitter traversal on Windows.
Cursor traversal and byte-derived row numbers allowed all 80 Python files
(1,570 symbols) to be indexed. A subsequent Ollama allocation failure was
avoided with the smaller embedding batch setting. Index construction in the
final attempt completed at approximately 186 seconds.

| Mode | Outcome | Line recall | Notes |
| --- | --- | --- | --- |
| T0 | Completed | 0 | No exact-match context emitted |
| T1 | Completed | 0 | Emitted 100 lines, no gold overlap |
| T2 | Incomplete exploration | Excluded | Reached the exploration step limit |
| Adaptive | Incomplete exploration | Excluded | Reached the exploration step limit |

The T2 trace contains three invalid actions and one query action across four
model calls. The runner returned exit code 1 and `all_passed=false`, retaining
incomplete modes outside the eligible frontier. Next work should inspect model
action validation and improve protocol adherence without changing gold labels
or treating incomplete exploration as a completed result.

This is a diagnostic single-instance run with reference region metrics and a
Python-only index. Official evaluator parity and public leaderboard performance
are not verified. Concurrent regression checks also make its timings unsuitable
for performance comparisons.
