# Astropy full repair v8: verified development continuation

On 2026-10-25 the user ran `.keel/repair-exploration/full-repair-v8/run.ps1`. Both runtime and fresh official harness grading passed for `astropy__astropy-14508`. This was an exposed saved-source continuation with historical diagnostic and block-rollback evidence, not a first-attempt or independent benchmark score (`benchmark_ready=false`).

Evidence: `.keel/swebench/astropy-full-repair-v8/trial.json`, `model-transcript.jsonl`, `run/trace.jsonl`, `final-grade/grading.json` and its per-instance report under `final-grade/logs`. Verified the per-instance report bytes against grading.report_sha256 `28193db849ef7ec132ecd498baa6f58b98a14840f44a740f6db649e9b6449b62`. Official run: `keel-1efa92004fc24e09b66b90a6d398f8b5`.

- Official target: 1 FAIL_TO_PASS success, 0 failures.
- Preservation: 174 PASS_TO_PASS successes, 0 failures, including test_invalid_float_cards2.
- Runtime: passed; failure=null; verification_rounds=1.
- Agent: 8 GPT-5.4 calls, 93163 tokens, 12 tools, 290.093s.
- Whole trial: 384.578s; outer watchdog passed at 390.062s.

The transcript records Critic replan, Scout localization, two probe proposals, a diagnostic answer and a model-authored edit. The inspected source preserves short decimal representations while normalizing scientific notation to uppercase E and maintaining exponent/width handling. The run used existing controlled comparison evidence to link the regression to str(value), rather than treating the unrelated historical failure as an untested baseline possibility. No developer business-source edit was made during this inspection.

Trace records eight token admission/usage pairs across Critic, Scout and Implementer with offline_tiktoken. This run did not stop at the previous capacity guard. Current runtime and counting policy differ from old v7, and model output is variable: this single pass cannot isolate tokenizer activation as the sole cause, prove stability, or demonstrate autonomous weight learning.

Review limitation: the exported prediction patch includes file-wide newline changes (visible CRCRLF additions), making the textual patch much larger than the logical formatter edit. Official application and tests passed, so this does not invalidate the observed grade; keep the exact accepted patch, and investigate transport normalization separately before any new export. An initial review mistakenly compared the aggregate harness report to the per-instance receipt hash; corrected by locating the per-instance report, which matches exactly. No historical artifact was rewritten.

Next: preserve this successful snapshot, prediction, inputs and implementation; perform an explicitly budgeted repeat from the same seed/runtime to measure stability before changing repair logic or claiming generalized improvement.
