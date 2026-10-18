# Compass navigation verification and fixed-trajectory selection ablation

Scope: development diagnostic, not independent quality validation or an online
Keel repair result. No original source artifacts or historical results were changed.

## Protocol checks

The real stdio probe at .keel/tool-checks/compass-overview-v1 failed before server
startup: the tool host denied SDK subprocess creation with PermissionError. It is
not recorded as a pass or a Compass retrieval failure. User-terminal verification
must use a fresh output directory, e.g. compass-overview-v2.

tests/test_compass_sdk_overview.py uses the installed official MCP SDK ClientSession
over its memory streams, sending real initialize/list/call/ping requests to Compass's
actual StdioServer.handle handler. It successfully returned Api and Api.fetch without
source bodies. Only the transport bridge differs; no mock server or tool result is
used. This verifies protocol/tool interoperability but not OS subprocess lifecycle.

## Selection replay

Command:

```powershell
python -m compass.selection_ablation --result .keel/swe-public/bdb1b28a48574f5fa371d7f53271854e/result.json --output-dir .keel/compass-selection-ablation/v2
```

The executed output is .keel/compass-selection-ablation/v2/selection-ablation.json.
Its inputs are the already-exposed Flask-5014, Requests-1724 and Seaborn-3069
development trajectories, not the newer official repair pilot. It pairs T1/T2 by
ranking, repetition, source budget and index identity. Source files, dataset rows,
runs, sweep metadata and replay implementation hashes are recorded. Rank/ID
validation rejects corrupt inputs. The same reserve_t1_candidates function is used
by online retrieval and replay; relevance labels enter scoring, not candidate selection.

All policies share a 100-unique-line output ceiling and 32-line per-symbol cap.
This is equal maximum budget, not equal actual emitted length. Thirty derived rows
cover two rankings, three tasks and five policies; there are still only three tasks.
Means below give equal weight to tasks.

| Code-aware policy | Line recall | Line precision | File hit rate | Mean emitted lines |
| --- | ---: | ---: | ---: | ---: |
| T1 | 3.164% | 42.667% | 72.222% | 100.0 |
| T2 original | 0.770% | 33.333% | 25.000% | 26.3 |
| T2 reserve 1 | 0.770% | 33.333% | 25.000% | 26.3 |
| T2 reserve 2 | 2.852% | 67.708% | 52.778% | 53.3 |
| T2 reserve 3 | 3.164% | 67.175% | 61.111% | 61.7 |

Reserving three restored T1's observed line recall on each of the three code-aware
tasks, but not its average file coverage. The extra emitted source is an important
explanation for the recall change. The one-seed policy did not help this sample.
RRF reserve-3 recall was 0.469%, still below RRF T1's 0.546%; precision was 13.121%,
below T1's 14.333%. Preservation is not a universal improvement.

Replay made zero new model calls. It retains original per-run usage in source_usage;
T2 policies still inherit their original model cost. Cached trajectory reuse cannot
prove future model behavior, rerouting benefit, total Keel token savings or repair
success. Prefix values 1/2/3 are reported together, not selected as a new default.
The default t2_preserve_top remains zero. Cheap T1 remains the necessary baseline.

Next: user-terminal stdio check; then freeze independent queries/tasks before any
live navigation or reserved-prefix quality comparison. Outline navigation must be
evaluated separately with observed source-reading actions and actual byte/token
accounting. It is not measured by this cached selection replay.
