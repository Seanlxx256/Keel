# Independent-issue 300/64 validation plan

The candidate 300-line total budget and 64-line symbol cap were selected for
further validation after the fixed-ranking budget replay. Existing defaults have
not changed. The next workflow excludes all three development-instance IDs from
`compass-final-policy-three-repo.json` before deterministic sampling with seed 42.
Exclusion source hashes are written in the plan before Git or model calls.

| Repository | New issue | Base commit |
| --- | --- | --- |
| psf/requests | psf__requests-1142 | 22623bd8c265b78b161542663ee980738441c307 |
| mwaskom/seaborn | mwaskom__seaborn-3187 | 22cdfb0c93f8ec78492d87edb810f10cb7f57a31 |

The verified plan-only run is at
`.keel/swe-independent/2361641f2a56473bac6cf905662ec472/`. Both snapshots were
missing at planning time. These are new issues in known repositories, not a
repository-held-out evaluation. Selection uses metadata eligibility and seeded
ordering, not measured retrieval scores. Once analyzed, these issues become
development data and must not be reused as untouched validation cases.

An actual preparation attempt at
`.keel/swe-independent/c0942f1712ff4232a10d8a9574476f33/` failed for both snapshots:
the agent's configured proxy `127.0.0.1:9` refused GitHub connections. Failures were
checkpointed; no model calls or independent-instance scores were produced.

Run on the user machine with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\examples\run_swe_independent.ps1
```

The workflow uses code-aware ranking and the read evidence policy, four modes,
one repetition, and the previous per-run tool/token/time limits. A fully successful
run has eight retrieval runs across two independent tasks. It then repacks the
same saved candidate rankings under budgets 100/300 and caps 32/64, making the
100/32 versus 300/64 comparison independent of model variance. These replayed
contexts do not measure downstream coding success or model behavior changes.

Reports and raw traces are preserved under `.keel/swe-independent/<run-id>/`.
Failure stops the wrapper before replay; raw per-instance failures remain visible.
Symbol caps are propagated through live evaluation, recorded in sweep metadata,
and treated as protocol settings when calibrating upgrades. Official evaluator
parity and generalization are unverified pending actual execution.
