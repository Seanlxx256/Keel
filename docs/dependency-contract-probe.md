# Static target-dependency contract probe

Purpose: inspect the actual installed package in a trial's frozen verifier image
before another paid repair run. This is not automatic patching, dependency code
execution, public API resolution or an acceptance result.

`keel.dependency_evidence` optionally includes direct methods for requested
top-level classes. Parameters come from parsed installed source; synchronous and
asynchronous definitions are distinguished. Distribution version must match,
source hashes and scan inventory are recorded. No package import occurs.
Methods inherited from bases and dynamic/reexport resolution remain unsupported.
Signature and doc fields have explicit bounds; a truncated signature is not a
complete callable contract. Method mode permits at most 60 matched records;
legacy top-level mode retains its 20-record cap. Existing scan byte/file/time
limits, Docker restriction and no-host-fallback behavior remain intact.

The new `referenced_calls` helper extracts direct calls through matching top-level
import aliases, including explicit from-import aliases. It does not guess receiver
types (such as `self._pool`) or replacement APIs. A name can refer to a function
or class; static definition lookup reports what is actually found. Complex import
rebinding, nested imports, inherited APIs and arbitrary dynamic code are outside
this helper's analysis. Empty/too-many requests fail rather than invent symbols.

## Run without LLM calls

```powershell
python examples/probe_dependency_contract.py --trial .keel/transition-trials/httpx-1588-localized-errors-v1 --distribution httpcore --module httpcore --output .keel/dependency-contract-httpcore-v1
```

The probe derives version and image from prepared.json, source paths from saved
changed_files, and requested symbols from actual candidate source calls. It
retains source hashes, scanner stdout/stderr, returned metadata and before/after
workspace equality. It never edits the previous candidate, reads gold code or
calls a model. Output directories cannot be overwritten. This is evidence from
an observed development patch, not an independent experiment or human-unseen
context. The module/distribution mapping is operator-specified; version is not.

The command has not been run against live Docker in the restricted tool
environment. The user terminal must validate it. Do not claim actual signatures
or successful target inspection until its result is available. Evidence has not
yet been wired into the localized trial's model input.

## User execution and optional runtime integration

The user executed the probe successfully in the fixed HTTPcore 0.13.0 image.
It scanned 30 files / 165,960 bytes and returned 48 records, with unchanged
candidate source and zero model calls. Actual static signatures include
`SyncConnectionPool.handle_request(..., extensions: dict)` and
`AsyncConnectionPool.handle_async_request(..., extensions: dict)`. This confirms
the method and keyword contract in the installed source, not overall repair
correctness, public reexport resolution or downstream response behavior.

The runtime now optionally accepts `localization_dependencies` only with
`localized-proposal`, for example:

```json
"localization_dependencies": [
  {"module": "httpcore", "distribution": "httpcore", "version": "0.13.0"}
]
```

After model-selected source localization, imported call symbols are inferred from
those selected files. The runtime rescans the fixed verifier image with ordinary
tool/time budgets; it does not reuse a previous candidate patch or its archived
probe as a new task's evidence. Projection retains public and protocol signatures
including constructors, declares the count of omitted private methods, preserves
distribution/version and inventory hash, and keeps raw scans in ledger/artifacts.
Truncated signatures are rejected. This filtering is not full API completeness.

Seven dependency-evidence tests, nine localization integration tests and thirteen
existing proposal tests pass (29 total). Tests check that dependency reference
data reaches the patch request, remains labeled untrusted, and does not replace
scope/patch verification. Real Docker scanning was verified by the user; the
combined runtime path has not yet been live-model tested.

## Capacity blocker, not a paid retry

Offline combining saved source/observations from `httpx-1588-localized-errors-v1`
with 24 projected public/protocol signatures yields a 13,288-byte proposal request
against the 12,000-byte cap. Artifact `.keel/contract-context-preflight-v1.json`.
No model was called. This does not show that every future selection overflows,
but does show that blindly appending all contracts is not a ready solution.

Do not prepare a paid trial using this combination or silently drop source.
Next investigate an explicit evidence-selection stage or bounded dependency
reading with provenance, accounting for any extra calls within the same budget.
No new overall repair outcome, default architecture change or expanded shell
permission is claimed.

Six evidence tests pass, including no-import method extraction, real parameters,
async definitions, version mismatches, bounded scans, invalid request rejection,
Docker-only collection and import-call inference. Existing 13 proposal tests also
pass. These tests do not prove the HTTPcore package exposes the scanned classes
through its public imports; live metadata and acceptance remain separate checks.
