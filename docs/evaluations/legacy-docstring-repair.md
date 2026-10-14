# Historical docstring parsing repair

On 2026-10-15, the Requests 1142 indexing failure was repaired without modifying
the pinned repository snapshot. The original and repaired index generations both
record SHA-256 `009bd8110fa3ac46eb2fe9ce0ccb88076ba2e3057d883cc78b37489d970133c9`
for `requests/packages/urllib3/contrib/ntlmpool.py`. Its status changed from
`parse_error` to `indexed`; the new index is complete with no diagnostics.

## Compatibility boundary

The parser first attempts normal Python AST parsing. Only a Unicode-escape syntax
failure activates compatibility handling. It finds malformed `\u`/`\U` escapes
in plain/Unicode triple-quoted string tokens, substitutes same-width ASCII spaces
in an in-memory AST input, and confirms that every affected literal is a genuine
module, class or function docstring. Literal values are restored with the malformed
escape preserved as text. Ordinary runtime strings and unrelated syntax errors
remain rejected. Tokenization failure also remains a syntax error.

Original bytes still feed tree-sitter, source fingerprints, signatures and code
chunks. Byte/line positions remain unchanged. The compatibility path permits
lexical indexing and does not make historical code executable under Python 3.
Incomplete indexes are no longer reused by the public runner; they rebuild after
the repair. This does not introduce a general Python-2 grammar backend.

## Execution evidence

The first repair run at `.keel/swe-independent/1bff32af396945b0937ef51469ba0a10/`
rebuilt Requests successfully, but one Requests T2 request returned model HTTP 500.
That original run remains incomplete. Seaborn completed all four modes there.

The separate Requests retry at `.keel/swe-public/6024829cffad43528f4f17844ce9d0ae/`
reused the now-complete index and passed all four modes. Together these provide
completed validation for both planned issues, not a claim that the first batch
passed. No original artifact or failure record was overwritten.

| Instance | T1 line recall, 300/64 | T2 line recall, 300/64 |
| --- | --- | --- |
| Requests 1142 | 8.04% | 0% |
| Seaborn 3187 | 7.27% | 1.43% |

Settings remain code-aware ranking, read evidence policy, one repetition, and
the original tool/token/time limits. The parser repair resolves index eligibility;
it does not resolve T2's narrow or incorrect evidence selection.

## Budget replay on completed instances

A derived source selection at `.keel/legacy-docstring-completed-analysis/`
records both source-result hashes and their original completion flags. It selects
the later successful Requests retry and the completed Seaborn instance, then
replays packing without model calls. The selection is based on completion, not
quality, and the HTTP-failed attempt remains documented.

| Total lines / symbol cap | Equal-instance mean T1 recall | Mean T1 precision |
| --- | --- | --- |
| 100/32 | 1.88% | 50.00% |
| 300/32 | 6.00% | 30.00% |
| 300/64 | 7.65% | 39.00% |

[The JSON archive](legacy-docstring-repair.json) retains the complete replay
summary, exclusions, source selection and hashes. This is two new development
issues in known repositories, with broad gold regions and only one repetition.
The budget gain is a fixed-ranking replay result; downstream coding success,
repository-held-out generalization, and official evaluator parity remain unverified.
