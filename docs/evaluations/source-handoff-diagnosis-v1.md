# Source handoff diagnostic pair v1

Known development context: astropy__astropy-14508, reconstructed from extended-v3
round one against the restored seed. One call per arm, fixed summary-first order.
No repair, Docker execution or probe was performed by this pair.

Plan SHA256: 97372b4f390d72b9a548f67d15ada6168d3ae1aaf34851d92908daaabf81c72f.
Both individual result receipts match their files and the aggregate report.
Inspection of frozen requests confirms identical system instructions and schema;
the only user-payload difference is source_handoff.

| Arm | Tokens | Calls | Seconds | Observed diagnosis |
|---|---:|---:|---:|---|
| Summary | 3,953 | 1 | 9.687 | Again requests the test body and creation path. |
| Source | 5,298 | 1 | 8.734 | Describes deliberate on-disk E-to-e mutation and warning-mode write; requests missing implementation and validation paths instead. |

Total: 9,251 tokens, 2 calls. Source costs 1,345 additional tokens. Timing is a
single noisy observation and not evidence of faster inference or lower total cost.

The source response uses details actually present in fact14 (test_header.py
2020..2065), and identifies fact21's _format_value dispatch as insufficient to
establish _format_float behavior. Both arms still choose replan. This is positive
qualitative evidence of source consumption and a more specific next inspection,
not proof of correct root cause, complete understanding of test phases or successful
repair. The source response does not explicitly establish which writeto call
raises; an expected-invalid phase must not be confused with an earlier valid setup.

The actual _format_float implementation was not included: whole windows were
omitted under the bounded handoff policy. It is legitimate to request genuinely
missing source. The next investigation should test targeted evidence acquisition
and matching stack frames to test phases, rather than sending the entire repository
or restarting global file localization. No task-specific fix belongs in production
logic. Prior forced-inspection failures remain relevant; do not enable that feature
by default based on this single pair.

Raw artifacts: .keel/repair-review/source-handoff-pair-v1/{plan.json,results/report.json}.
Generalization requires additional cases; no automatic quality score is assigned.
