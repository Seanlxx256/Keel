# Offline token counting activation

Implementation support is not activation. A configured encoding and an installed counting engine must exist in the actual host interpreter. The setup tool below intentionally makes this explicit; it does not use the model credential or call the model API.

Run from the repository root using the same interpreter that launches the Agent:

```powershell
& 'D:\code\monocular_depth_estimation\.venv\Scripts\python.exe' examples/prepare_token_counting.py --model-config .keel/model-openai.json --policy .keel/repair-exploration/full-repair-v7/context-policy.json --output .keel/token-counting/v1 --install --transcript .keel/swebench/sphinx-9602-probe-informed-v3/model-transcript.jsonl
```

`--install` explicitly installs tiktoken into that interpreter environment. Setup may download package/encoding assets. It uses the library's model mapping, stops on unknown mappings, records package version/encoding identity, and exports an offline JSON encoding. It never guesses from a historical byte/token ratio. Mapping source: [official tiktoken model registry](https://github.com/openai/tiktoken/blob/main/tiktoken/model.py).

Pip/export/calibration child stages share a180s budget, have per-stage timeouts and10s progress updates, and use the shared CommandRunner. Required stage/report artifacts persist; an existing output is refused. Export is verified in the parent interpreter before success. No implicit package install or asset download takes place during ordinary runtime estimation.

Generated `policy.json` preserves all original capacity/safety limits and adds:

- `local_tokenizer`: exact exported asset path;
- `local_tokenizer_sha256`: bound asset identity;
- `require_local_tokenizer: true`: fail explicitly instead of silently falling back to bytes;
- `recover_capacity: true`: bounded lossless repacking.

Runtime caches one built encoding but rechecks asset bytes/hash on each estimate. Missing dependency, corrupted assets or changed identity stop strict preflight. The old optional mode still records its byte fallback for compatibility. A strict policy must be used by the same host interpreter or another interpreter with the counting dependency installed. Existing policies and frozen runs are not rewritten.

## Runtime coverage

With `agent.proposal_context_policy` configured in the proposal workflow, shared policy reservation now covers file/definition localization, its Scout tool exploration, Critic recovery routing, diagnostic calls and existing Implementer proposals. Scout/Critic estimates and actual prompt usage are traced. No policy retains the legacy path. General workflows that do not enable this policy are not automatically migrated.

Role calls use the same Budget, output and safety reservations; there is no new budget per role. Denied policy-based requests record raw messages/schema and typed incidents before any recovery dispatch. True byte ceilings are still enforced before counting; enabling token counting does not bypass them. Strict encoding preflight runs through proposal_context_limits before costly task execution.

Counts are local text estimates, **not provider-exact message/tool/schema accounting**. Calibration must compare against actual prompt usage, not total input+output usage. Keep safety reserves and record deviations; do not automatically adjust limits or assume end-to-end success. The setup's optional transcript calibration measures old dispatched requests, not missing historical denied requests.

## Validation boundary

124 related tests passed21.459s. Tests use a synthetic counting engine to verify wiring, strict failures, cache identity, shared two-role budget/usage records and Scout tool-loop behavior; fake-engine export verifies strict policy generation and unchanged limits. Setup subprocess tests verify planned stage arguments/timeouts without installing anything. An initially misspelled test-module selection was corrected; final suite passed.

Actual package installation, asset export and calibration using real tiktoken are pending execution in the user environment. No new API, Docker or repair acceptance was run by the developer. Review `.keel/token-counting/v1/report.json`, `export.json`, `policy.json`, and `replay/report.json` before using the new policy for a frozen repair experiment.

## Export-log collision recovery and actual activation (2026-10-25)

The first real preparation installed tiktoken0.14.0 and exported a valid o200k_base asset. The parent then wrote its subprocess result to `export.json`, overwriting the child's metadata under the same filename. Verification failed with KeyError despite successful installation/export. This was a setup implementation bug, not a model/tokenizer failure. Previous mocked stage tests did not exercise this intermediate write.

Process logs now use `install-process.json`, `export-process.json`, `calibration-process.json`; `export.json` is exclusively metadata. The new regression executes simulated worker export followed by the real parent log write and strict verification, reproducing the formerly missed interaction.

Explicit `--recover-from` prepares a **new output** from prior assets. It verifies source stage completion, original model/base-policy identities, model-to-encoding mapping, artifact hash and unchanged capacity parameters. It copies identical encoding bytes, reconstructs clearly labeled metadata using the current installed engine, then verifies offline and calibrates. It does not claim to restore the lost original metadata, and does not install or use the network-capable encoding resolver. Source failures/logs remain unchanged.

Actual recovery already completed in `.keel/token-counting/v2` using the user's existing interpreter: export/calibration exit0, offline_tiktoken selfcheck,2.469seconds,0providercalls,no reinstall/download. Strict new policy `.keel/token-counting/v2/policy.json` binds encoding SHA4029c3ac56de9d29db7c4b38c1148e9e6ffaa1a5fdd1ddd3c494d68694098d41. The v1 failure remains preserved. This supersedes the earlier pending-activation statement for this interpreter and this new policy only.

| Historical request | New local estimate | Recorded input usage | Ratio |
|---|---:|---:|---:|
|1|9124|8122|1.123|
|2|8628|7920|1.089|
|3|5863|5421|1.082|

This is a major improvement over byte estimates of32956/34872/23838 on the same saved inputs, **not a reduction of billed historical usage**. Safety/framing uncertainty remains and policies/old trials were not automatically replaced. No new model repair or SWE-bench acceptance occurred.126relatedtests passed21.170s, including collision and no-resolver recovery/immutability/drift checks.
