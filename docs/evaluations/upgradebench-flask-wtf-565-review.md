# Flask-WTF #565: cross-repository candidate

Primary source: https://github.com/pallets-eco/flask-wtf/pull/565/files

The merged PR addresses Flask/Werkzeug 2.3 deprecations in reCAPTCHA widgets
and validators. This candidate deliberately targets released Flask 3.0.0 and
Werkzeug 3.0.0, where obsolete imports are absent. It does not reproduce the
original dependency environment. It adds a repository and a two-source-file
change, but remains within the Python web ecosystem.

## Reproduce before model execution

```powershell
python examples/reproduce_flask_wtf_565.py --build-image
```

Docker Desktop must be running. No model/API key is used. Read-only GitHub API
requests may use the existing `GITHUB_TOKEN` environment variable; never paste
its value into chat. Responses are archived with hash receipts using the existing
collector, with bounded connection retries and redacted error diagnostics.

On first execution, the script resolves merged PR metadata and freezes full
merge and first-parent hashes in `metadata.json`. It does not use the mutable
PR base-branch SHA. Both snapshots must be clean. The Git object's parent must
match the frozen metadata, and its exact diff inventory must match the four
upstream paths: two sources, one test and one changelog. These checks verify
consistency, not cryptographic authorship of GitHub metadata.

The dependency image has eight exact package versions and runs `pip check`.
Flask-WTF is not installed from PyPI: the probe imports the checked-out `src/`
package and checks its path. Both revisions run with the same resolved image ID
inside the existing nonprivileged, read-only, network-disabled Docker verifier.
The Python base tag and dependency wheels are not hash-locked for portable
rebuilding.

Four curated cases cover import, widget rendering, query parameter encoding
and form rendering. They never contact Google's reCAPTCHA service and do not
cover live validation or the full upstream suite. Every base case must fail
with a specific obsolete-import error; all gold cases must pass with matching
exact dependency versions. Missing/duplicate cases, unrelated errors and
timeouts fail assessment.

The printed directory retains metadata, logs and partial execution results.
To reuse frozen metadata after interruption:

```powershell
python examples/reproduce_flask_wtf_565.py --metadata PREVIOUS_DIRECTORY/metadata.json --build-image
```

For a fully cached rerun with an existing image and both snapshots, use
`--metadata PREVIOUS_DIRECTORY/metadata.json --offline` without `--build-image`.
Metadata is trusted curator input; reuse the archived file without editing it.

## Status

User-side reproduction passed on 2026-10-15 at
`.keel/upgradebench-reproduction/60f3db38a28b4bed9585ad4f22f1877d`.
Frozen base: `2d80102a5d85ef5cae3a3994ca4cb75679165ba2`;
gold: `dfd18bad39048fe1e076b5b64fc2adbd8f44e2c2`.
All four base cases failed on the removed Flask Markup import; all four gold
cases passed in the same dependency image, without timeouts. Image ID:
`sha256:7eb540a99d15f5c29ab6dced54e340888c0d236f4782f009ad996d727fa9c99d`.
The base/gold snapshot range was rechecked during local task preparation.
Probe hash: `a9b8769257a608a1bb54a42f0aaffd47d08c085d06d4673990b6c55baac36bc8`.
Summary hash: `1f209b1c000832e4c5ff1b8ddf069e178d08b64e1216aa0162e105f8c5fc0b13`.

The diagnostic suite now accepts `--case flask-wtf-565`. Preparation exports
only base files, declares widgets.py and validators.py as the allowed source
scope, and excludes gold revisions/patches from the model request. Nonempty
changes confined to declared files are required, followed by independent Docker
acceptance; modifying every allowed file is not itself a success criterion.
The unchanged 12000-byte input cap is checked before execution: preparation
`.keel/agent-baseline/5dae2ae775134575ade622ad941b6f04` reports 5545 input bytes.

First model run (paid, using the already configured service):

```powershell
python examples/run_agent_baseline.py --case flask-wtf-565 --reproduction .keel/upgradebench-reproduction/60f3db38a28b4bed9585ad4f22f1877d --strategy proposal --group real_compatibility --model-config .keel/model-openai.json --execute
```

The successful probe does not execute the validator's outgoing request path.
Thus even a model pass is only curated import/rendering acceptance, not proof
that all reCAPTCHA validation behavior is preserved. Broader acceptance is
required before considering benchmark readiness.

First model repair `.keel/agent-baseline/859a335cb53340e98053b7eca99beeab`
failed acceptance: one call, 1674 reported tokens, 11.563 runtime seconds and
14.281 including baseline. Only widgets.py changed. Markup's import was fixed,
but url_encode remained in widgets.py and validators.py was unchanged. All four
final cases failed on the removed Werkzeug import. This is an incomplete repair,
not a protocol failure. Preserve it in first-attempt counts.

One explicit follow-up is now available:

```powershell
python examples/run_agent_baseline.py --case flask-wtf-565 --reproduction .keel/upgradebench-reproduction/60f3db38a28b4bed9585ad4f22f1877d --strategy proposal --group real_compatibility --model-config .keel/model-openai.json --feedback-from .keel/agent-baseline/859a335cb53340e98053b7eca99beeab --execute
```

This exports a fresh original base workspace, supplying the previous patch and
bounded observed errors as untrusted feedback. The model must generate the
complete corrected edits against that original source. No gold patch or human
replacement hint is inserted. Source, model, image, acceptance and scope must
match; case identities and dependency versions are checked. Timeout, recursive
feedback, non-verification failures and oversized patches are rejected.
Preparation succeeded at `.keel/agent-baseline/f87e15388b064d57b58705175548f4df`;
The follow-up at `.keel/agent-baseline/1e701e1b787746c79c3f0b96aaaa58f9`
failed patch validation: edit index 4 matched zero occurrences. The model
selected a plausible replacement API but invented an old `values = dict(...)`
snippet instead of using the actual multiline dictionary call. Entire-batch
validation prevented all writes, including the preceding valid edits. One
call, 2321 tokens, 9.594 runtime seconds and 12.453 including baseline. Across
both attempts: two calls, 3995 reported tokens, 21.157 runtime seconds and
26.734 seconds including the separate baselines. No repair success is claimed.

Inspection also found an evidence defect: a function-definition query returned
only nearby lines and omitted the validator's later url_encode call. The source
evidence builder now includes the full body of functions whose definition line
matches a query, while preserving exact source text and the existing input cap.
Oversized bodies fail the same preflight rather than silently truncating the
tail. This is generic source-driven expansion, not a gold-derived replacement.
The current original-source input is 6248 bytes (previously 5545), and both
url_encode call sites are visible. A regression test verifies tail inclusion,
source-range fidelity and unchanged cap enforcement. This change has not been
tested in another live inference. Do not erase either failed attempt or describe
a future run as untouched evaluation or an additional independent task.

This is attempt two on the same task, not additional coverage. Reports link
prior artifact hashes and budget. Total experiment cost includes both attempts.
Each invocation uses a fresh per-attempt budget; this is not shared-budget
automatic recovery or an isolated feedback ablation. Safety and acceptance
remain unchanged.

Five offline tests cover metadata resolution, parent/diff verification, probe
syntax, strict assessment and multi-file base-only task export. Additional
suite/comparison regressions pass. `benchmark_ready` remains false. Retain
unsuccessful attempts; do not turn these exploratory tasks into a general
resolve-rate claim.
