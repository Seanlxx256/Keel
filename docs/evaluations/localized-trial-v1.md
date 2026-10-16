# First hierarchical proposal trial and combined-map capacity

User run: `.keel/transition-trials/httpx-1588-localized-v1`.
Strategy `localized-proposal`, unchanged source, no edits. It failed in Scout
before the anchor-selection provider request. File selection used one model
call, 408 tokens; runtime 9.047 seconds, six tool calls. No patch call or
acceptance pass. This is a development failure, not an independent test.

The saved model selected five files: default transport, client, API, models and
content modules. The combined verbose symbol map grew to 19,889 bytes, exceeding
the unchanged 12,000-byte request cap. Individual-file capacity checks were not
a guarantee for this combination; the earlier documents explicitly limited
those results to single-file scenarios.

## General representation correction

Per-symbol objects repeated the same file path in every `location` string plus
field labels for name and line. The current structure groups `[line, name]`
pairs under one file path. It retains all definitions rather than dropping lower
ranked files, truncating symbols or increasing the cap. The model still returns
exact `path:line` values; host validation uses the same full set of positions.

Offline replay of the **same saved five-file choice and task goal** now builds a
7,318-byte complete structured anchor request with 266 definitions. The old
19,889-byte value is structure-only and the new 7,318-byte value is full request;
do not present their ratio as an exact equal-boundary percentage reduction.
The early exploratory estimate before the final instruction change was 7,228;
7,318 is the recorded current-format value.

Artifacts: `.keel/localization-selected-replay-v1.json`. The replay tool verifies
the prepared source inventory, reads the ledger in read-only mode, preserves the
saved selection and records hashes. It makes no model requests. Rerunning it
requires a new output filename:

```powershell
python examples/replay_localization_selection.py --trial .keel/transition-trials/httpx-1588-localized-v1 --output .keel/localization-selected-replay-v1.json
```

The update includes an equivalence test for all names/lines, nested definitions
and duplicate names. Localization (7), context measurement (1), exact source (2),
proposal (13) and runner (4) tests pass: 27 relevant tests. It is not a new live
repair result. The selected patch contexts can still exceed the cap, and another
model file choice can produce a different combined-map size. No silent exclusions,
new permissions, default-mode replacement or overall runtime-success claim.
