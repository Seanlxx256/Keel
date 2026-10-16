# Development v3: localization pass, no feedback gain

Source: `.keel/repair-comparisons/development-v3`. Two known development tasks, one generation per arm. Both final rates are 1/2, with Starlette passing and Flask-WTF failing. No held-out or statistically reliable gain is established.

Both Starlette arms used four model calls and one verification round. This is consistent with localization refinement followed by an initial successful patch, not a verification-feedback recovery. The formerly observed capacity failure did not occur in these two generations; this does not guarantee all future selections fit.

Flask-WTF disabled generated a syntactically valid patch that left an incompatible import; all four acceptance cases failed. Enabled generated a patch batch with missing trailing newlines, causing Python statements to concatenate. Host AST parsing correctly rejected the batch before any write; no acceptance command ran. It also proposed importing an incompatible dependency API, so correcting newlines alone would not establish task success.

Generic correction after this observation: when verification repair is enabled, each proposal may receive one validation retry for malformed JSON, exact-match/edit-shape problems or Python syntax errors. The model receives the rejected batch and host error against unchanged evidence and resubmits a complete batch. The host does not auto-correct snippets, indentation or newlines. Policy/audit/stale-source/provider errors are not retried by this mechanism. All attempts share the original budget and context cap. Failed batches are logged and never partially written. Verification feedback remains necessary for valid-but-wrong code.

The one validation retry is available per proposal, including later verification repairs, bounded by the original total model budget. Default runs with verification repair disabled retain zero validation retries. The enabled/disabled comparison now tests a broader recovery package, not solely post-verification feedback; future reports must identify that scope change and must not pool these implementations as identical arms.

Four regression tests cover correction from an invalid batch, exhausted shared budget, no retry after policy denial, and a repeated invalid batch stopping without writes. Existing proposal/localization/recovery suites also passed. No new paid run or Flask-WTF success is claimed by this change.
