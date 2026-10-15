# Static dependency API evidence

Optional `proposal.dependencies` requests static definitions from installed
distributions in the same Docker image used for verification. This supplies
target-environment evidence rather than a reference repair or guessed API name.

```json
{
  "distribution": "anyio",
  "version": "4.0.0",
  "symbols": ["start_blocking_portal"]
}
```

Requests are operator supplied, not executable model arguments. There may be
at most three distributions and eight Python identifiers per request. The
collector requires Docker and uses the existing read-only, nonprivileged,
network-disabled runner with a maximum 30-second scan timeout. It charges the
shared tool budget and records execution artifacts and correlated trace events.
There is no host fallback or dependency download.

`python -I` prevents the workspace from shadowing scanner imports. The scanner
uses standard-library distribution metadata and AST parsing; it does not import
the target package or execute its functions. It checks the exact installed
version and scans only inventoried Python files under the installation root.
Limits are 200 files, 2 MB per file, 5 MB total and 20 matches. Exceeding a limit,
missing inventory, parse/read failure or wrong version fails visibly instead of
presenting a partial scan as complete.

Evidence includes the distribution/version, file/byte counts, inventory hash,
and matching top-level definitions with module path, line, bounded signature,
first docstring line and source hash. A record is a static definition, not proof
of a public runtime export or compatible behavior. Reexports, conditional/nested
definitions, dynamically generated APIs and method traversal are not resolved.
An empty result therefore does not prove a symbol is unavailable. Signatures
and descriptions are bounded; signature truncation is explicit. All returned
source-derived text is untrusted reference data.

Raw scan executions are saved in `run/dependency-evidence/<index>.json`; ledger
facts and `dependency_scan_started`/`dependency_scan_finished` events connect
them to Scout. Records enter the same bounded proposal input; they do not widen
file write scope, authorize commands or bypass audits/acceptance. An oversized
combined input fails before the model call.

## Starlette experiment

```powershell
python examples/run_agent_baseline.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9 --strategy proposal --group real_compatibility --dependency-evidence --execute
```

Only the unresolved real task is selected. The configured request uses the
already selected target version and symbol from the original error; it does
not specify the replacement module or read the gold patch. The fixed Docker
image supplies any matching definitions. Goals, base source and acceptance stay
unchanged, while evidence presentation is a newly recorded experimental factor.
Without `--dependency-evidence`, previous proposal behavior remains available.
Reports expose scan/match counts; complete records are in the saved evidence.

Four scanner/collector tests verify nonimporting source discovery (a fixture
package raises if imported), version mismatch, absent symbols, size limits,
request validation, budget charging, saved executions and identity checks.
Proposal integration verifies evidence reaches the prompt without widening file
scope. The real experiment is prepared, but no live target-image scan or
Starlette repair success is claimed yet.

## First live evidence-backed attempt

Artifact: `.keel/agent-baseline/8b284c6959e04352a596aa89f100daef`.
The fixed image scan completed successfully: AnyIO 4.0.0, 37 Python files,
305912 source bytes and one matching top-level definition. It located
`start_blocking_portal` in `anyio.from_thread` at line 369, with signature and
source hash. The inventory hash is
`538bd372494c28e59de4d0fcf39acab66b42bbf2f0060700bcc0d3bb7936bd6b`.
This verifies the evidence path against the real target image, independently
of the reference patch.

The one-call proposal still failed. It supplied identical old/new strings,
`from anyio import start_blocking_portal`, which are absent from the repository
source. Thus it was neither a valid source match nor an effective change. The
host rejected it before writes; no fuzzy matching would turn an identical
old/new entry into a repair. This is not merely a newline/formatting problem.

Recorded cost: one model call, 1350 reported tokens, 27.828 runtime seconds,
5132 peak request bytes and no context compaction. Real-task success remains
0/1 for this configuration. Evidence retrieval worked; reliable migration
reasoning and edit generation remain unproven for the current 3B model.

Do not keep tuning prompts or weakening match validation around this one task.
The next discriminating experiment is a stronger-model comparison with the same
sources, dependency evidence, acceptance and budgets, retaining the current
failure as baseline. Alternatively resume other planned infrastructure work;
this result does not justify claiming real-task resolution.
