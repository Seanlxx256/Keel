# Full repair v4 accepted, 2026-10-23

Evidence: `.keel/swebench/astropy-full-repair-v4/trial.json`,
`run/trace.jsonl`, `run/changes.patch`, `final-grade/grading.json` and official
per-instance report under final-grade/logs/run_evaluation.

Runtime passed, official_resolved true, no failure/infra/grading error. Target
FAIL_TO_PASS1/1 and preservation PASS_TO_PASS174/174. One verification round.
Model generated normalization helper handling short and fallback representations;
new attempt modifies card.py. No host repair inserted.

7calls,77,917tokens,11tools,308.328agent seconds (includes verification),498.281
total trial seconds. Only saved-failure assessment used a recovery action; no
source-reselection loop. Compared with prior acceptedv2:8calls/93,158tokens/
19tools/521.375total seconds. Descriptive run totals, not a controlled cost claim.

Configured proposal soft48,000/hard52,800. Actual proposal_context_admitted input
47,891bytes,headroom_used0. This live run validates successful operation with the
policy configured, but does not exercise above-soft admission or establish that
extra4,800bytes caused success. That branch remains locally tested. Sampled
context/model choices and lossless serialization also differ from the failedv3.

Scope: another developer-assisted exposed saved-candidate continuation, not a
first-attempt score or held-out generalization. V2 andv4 accepted,v1 andv3 failed;
keep every attempt and cost. Freeze successful artifacts; next evaluate independent
failure checkpoints and targeted boundary cases rather than repeatedly tune here.
