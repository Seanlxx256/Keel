# Historical proposal capacity replay: 2026-10-25

Read-only inputs: actual dispatched proposal requests in:

- `.keel/swebench/astropy-full-repair-v4/model-transcript.jsonl`
- `.keel/swebench/astropy-14508-bounded-30min-v4/model-transcript.jsonl`
- `.keel/swebench/sphinx-9602-probe-informed-v3/model-transcript.jsonl`

Receipt and measurements: `.keel/repair-review/token-capacity-replay-v2/report.json` and `receipt.json`. Implementation/source hashes recorded. Earlier v1 report is preserved; v2 adds observed usage pairing. No provider or Docker calls, changes to old transcripts, budget expansion or acceptance regrading.

## Findings

13 recorded proposal requests were measured with the same registered compactor now used in production. Non-goal payloads (including source evidence, allowed files and diagnostic fields) and system instructions remain identical. Goal transformation uses the existing exact execution-wrapper deduplication, retaining child results. Raw transcripts remain unchanged.

Conservative input estimate before:333742; after:331893; reduction1849, **0.554%**. These are UTF-8-byte fallback units, not actual tokens or billed savings. Existing requests often already contain compact request views. This is useful at small margins but does not demonstrate recovery of a request exceeding available space by thousands of tokens. Do not describe any of these dispatched requests as the exact previously rejected request.

All13 have reported total usage; only3 include separately recorded prompt tokens:

| Conservative estimated input | Observed prompt tokens | Estimate / observed |
|---:|---:|---:|
|32956|8122|4.058|
|34872|7920|4.403|
|23838|5421|4.397|

Another request estimates47917, while the reported **input+output total** is13194. This also demonstrates conservative overestimation for that sample but does not identify its exact input count.

The first three ratios include serialization/schema differences and are not portable token conversion constants. They must not be used to divide future estimates by four or expand authorization. Accurate offline encoding plus explicit framing/schema safety and observed calibration is the next priority.

The inspected current `full-repair-v7/context-policy.json` has no local_tokenizer entry. Both harness-v3 and the user launcher virtualenv reported tiktoken unavailable via module-spec checks. Thus implementation support exists without being activated in these inspected environments/configuration. This is not a claim that every historical snapshot used the same environment.

## Scope and next work

The replay measures saved **dispatched** proposal requests only. Pre-dispatch denied requests can be absent from model transcripts. Historical insufficient-token failures often occurred in Scout, while the new bounded repacker is currently connected to policy-enabled proposal calls. Consequently this result neither establishes that all early stops are fixed nor that old tasks would pass with different admission.

Next connect reliable offline token counting to actual enabled configurations and role call paths, retain explicit byte/token distinctions and rejected-request checkpoints, and compare measured estimates to provider prompt usage before claiming effective budget recovery. Do not start another full repair experiment based only on the 0.55% layout saving.

Reusable tool: `examples/replay_request_capacity.py` with repeated --transcript arguments and a new --output. It executes no model/tool experiments, enforces a60s cooperative deadline and read envelope, preserves source hashes, refuses existing output, records unsupported inputs distinctly and pairs usage only with the immediate recorded successful response. Tests and shared production regressions:97passed17.154s. This includes the existing production Workspace recovery test; no new live model self-correction is asserted.
