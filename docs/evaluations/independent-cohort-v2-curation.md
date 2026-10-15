# Candidate cohort v2: no executable upgrade tasks established

Collection: `.keel/independent-candidates/b1faa17118f54ef29d51ef40d24705fb`.
Static review: `.keel/candidate-review/885ff93ac50644fc9c5c5177827d5513`.
The fixed selected cohort contains Click #9, pytest #7832 and Requests #4204.
User-side static review verified clean pinned snapshots, first-parent identities
and source inventories. All three remain in the cohort; no reserve is promoted.
There were no model calls, environment probes or independent repair scores.

| Candidate | Observed source evidence | Curator disposition |
| --- | --- | --- |
| Click #9 | Moves top-level fcntl/termios imports into the ioctl helper's try block | Exclude from dependency-upgrade track: platform compatibility, no identified dependency upgrade target |
| pytest #7832 | Removes pathlib2 branch for Python <3.6 and the corresponding conditional dependency; setup.cfg already requires Python >=3.6 | Exclude from this track: unsupported-version compatibility cleanup, no identified supported target-environment failure |
| Requests #4204 | Changed source hashes but identical parsed Python AST | Exclude under the recorded no-AST-change rule; title explicitly describes a compatibility comment correction |

These are source-based curator dispositions, not measured base-green outcomes.
In particular, no unsupported Python version, missing stdlib module simulation
or unrelated Linux acceptance may be introduced to manufacture base-fail/gold-pass.
Click's change may be a legitimate Windows bug fix, but that does not make it
a dependency-upgrade task or establish Windows reproduction in Linux Docker.
AST equivalence does not prove every observable behavior is identical.

The sampled metadata did not establish any usable dependency-upgrade tasks.
`independent_tasks_ready` remains zero. Do not report a zero model resolve rate:
no valid model task was executed. Report discovery/curation yield separately
from model performance, retaining this unsuccessful cohort.

## What this changes in the next experiment

The title keyword "compatibility" was too broad: it retrieved comments, platform
changes and obsolete-version cleanup. Seeded sampling is reproducible but does
not fix weak candidate validity. This was a discovery design limitation, not
evidence of model/runtime repair quality.

A future separately versioned discovery policy must require an identifiable
dependency transition or documented removed/deprecated API in a supported target
environment. Manifests alone are neither necessary nor sufficient; deprecation
fixes can change source without changing requirements. Before inference, require
exact target versions, reproducible installation, independent functional
acceptance, baseline failure attributable to that transition and reference pass.
Keep human curator assistance and source localization explicit.

Freeze that policy before collecting a new cohort. Do not merely exclude the
three observed bad titles or hardcode a better replacement PR. The next step
is to define dependency-transition evidence requirements and discovery inputs,
not to keep constructing bespoke probes for this fixed cohort.
