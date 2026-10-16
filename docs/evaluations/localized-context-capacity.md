# Single-file and function-anchor capacity audit

2026-10-16. Output: `.keel/localized-context-capacity-v1.json`.
No model, Docker, credentials or network calls. Each writable Python source in
three existing development base snapshots was checked; no gold files, changed
file lists or reference patches were used for selection. Original files matched
their before/after inventories.

| Repository | Single-file symbol requests fitting 12KB | Function-name source requests fitting 12KB |
| --- | ---: | ---: |
| HTTPX 1588 base | 22 / 22 | 242 / 271 |
| Starlette 1936 base | 35 / 35 | 325 / 337 |
| Flask-WTF 565 base | 15 / 15 | 43 / 43 |

The audit reuses `selection_request` and `proposal_request` from runtime, so
system text, serialized messages, output schema and source-window behavior are
included. Goal text is generic and requests are structured; actual task text or
provider JSON-object schema injection can change bytes. This is not exact token
counting or the full HTTP request size. Each function name is checked separately,
deduplicated within each file. These are hypothetical selections, not tasks or
actual model predictions. Multi-file/multi-anchor selections may be larger.

Some short-name queries match many places in a file. Examples include HTTPX
`httpx/_client.py` / `headers` (35,844 request bytes) and Starlette
`starlette/routing.py` / `route` (20,572 bytes). The current literal matcher adds
all matching neighborhoods and complete functions whose definition lines match.
Names can therefore gather unrelated definitions or references. Long individual
functions can also exceed a cap independently of name ambiguity. The audit does
not establish how often a live localizer would choose these names.

## Decision

First-stage path selection fixed the full-map capacity issue, but did not solve
all downstream source-context cases. Do not call the full pipeline universally
ready or silently truncate source. Next opt-in prototype should identify symbols
by explicit source locations and validate that selected positions correspond to
the structure shown to the model. Keep source hashes, protected-path checks,
global budget and final patch verification. Operator-localized proposal behavior
should remain unchanged for historical comparisons.

One new test checks that a large function is reported as over-cap while a small
function fits, protected tests are excluded and source bytes stay unchanged.
Together with localization (5), proposal (13) and first-request measurement (1):
20 relevant tests passed. No live performance gain or automatic task success.

## Exact definition-location variant

The optional localizer now exposes exact `path:definition_line` identifiers and
accepts only a selection from that displayed set. Evidence includes the file
preamble and complete chosen definition/decorators. Source hashes must still
match between selection and collection. Large definitions are not truncated;
cap overflow remains an error. The old proposal query behavior is unchanged.

Offline output `.keel/localized-context-capacity-v2.json` contains both the
literal-name baseline and individually selected function/method definitions:

| Repository | Literal-name queries fit | Exact definitions fit |
| --- | ---: | ---: |
| HTTPX | 242 / 271 | 417 / 417 |
| Starlette | 325 / 337 | 474 / 474 |
| Flask-WTF | 43 / 43 | 46 / 46 |

Units differ: duplicate names are one baseline query but multiple exact
definitions. This is not a paired task success-rate comparison. All single-file
symbol-selection requests still fit under the updated location schema. Class
selections and combinations of multiple definitions/files can exceed the cap;
the successful single-definition probes do not establish full-pipeline readiness.
Goal text, model choices, missing imports/parent context and actual API reasoning
remain untested. No provider calls occurred; inventories stayed unchanged.

Two exact-evidence tests cover duplicate-name disambiguation, decorator/source
fidelity, invalid positions and refusal to truncate a large function. A new
integration test rejects source drift during location selection before patching.
Localization (6), exact evidence (2), proposal (13) and both measurement suites
(1 each) passed: 23 tests. This tests host behavior, not model selection accuracy.
