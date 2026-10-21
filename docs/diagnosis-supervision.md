# Optional diagnosis consistency supervision

Enable `recovery.diagnosis_supervision=true` with adaptive recovery, or the SWE
runner flag `--diagnosis-supervision`. Default is off. It does not enable forced
inspection or require progress monitoring. Source evidence is available only when
actually present in the Critic observation (for example via source handoff).

After a non-stop Critic diagnosis, a separate model request reviews only the
diagnosis and its evidence catalog. The request has a separate context but uses
the same configured model/client. This is not a seventh autonomous Agent or an
independent source of truth. No private chain-of-thought is requested.

Evidence includes observed caller frames, exception excerpts, stdout/stderr tails
and any delivered source windows. Only a conflict verdict may contain findings.
Each finding must quote an exact substring from a named diagnosis field and from
a supplied evidence item. Host checks references and quote presence; semantic
incompatibility is still a model judgment. Missing evidence is not a proven conflict.

The reviewer returns consistent, conflict or insufficient. Consistent means no
identified contradiction, not that causality, patch correctness or acceptance has
been established. Insufficient leaves the ordinary tentative repair/replan route
and normal verification constraints in force. The supervisor cannot write files,
run commands, change acceptance, add permissions or mark a task passed.

For conflict, Critic gets one correction request containing the specific findings.
If it stops, stop is respected. Otherwise one final review checks the corrected
diagnosis. A persistent conflict raises RecoveryStopped and preserves evidence;
there is no open-ended review loop. The supervisor adds one call normally, or up
to three for conflict/correction/recheck, sharing global model/token/time limits.
Existing targeted source reads or malformed-response recovery have their own
bounded behavior; this flag never resets those budgets.

Calls, raw reviews and decision IDs are recorded in the ledger/trace, and
recovery reports include supervision_reviews. Review results are untrusted model
assessments. Budget/capacity failures stop explicitly. Existing candidate retention
and independent verification/audit remain responsible for task outcome.

Validation uses scripted models: exact citations, fabricated-citation rejection,
default-off behavior, insufficient evidence, correction, persistent-conflict stop,
stop during correction and shared budget exhaustion. A runtime integration test
executes real local acceptance checks on a synthetic fixture: failed edit,
supervised correction, repaired edit, passing verification. This proves control
flow, not real mini review quality or SWE-bench success. No new paid model or Docker
run was made during implementation. Real efficacy requires a frozen bounded trial.
