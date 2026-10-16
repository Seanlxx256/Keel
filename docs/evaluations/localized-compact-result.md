# Compact-map localized trial: patch generated, verification failed

Artifact: `.keel/transition-trials/httpx-1588-localized-compact-v1`.
Three model calls, 5,247 tokens, 15 tool calls, 23.172 runtime seconds.
The saved patch changes only `httpx/_transports/default.py`: two `ext=` keywords
become `extensions=`. Sync and async pool entry points remain `request` and
`arequest`. All four API cases still fail with the original missing-interface
AttributeErrors. No acceptance criteria or reference patch were modified.

This is `edited_but_trial_failed`, not `no_edit_attempt` and not task success.
It demonstrates the new path can traverse autonomous localization and exact
editing on this development task, but does not demonstrate repair reliability,
causal speedup, cost savings or superiority over multirole execution.

File selection identified five plausible files. Exact-location selection included
the relevant sync/async transport methods and two client request methods. The
model-generated patch therefore had relevant source available but changed only
one part of the migration. It would be speculation to attribute this entirely
to the model, retrieval or absent dependency documentation.

## Observed input gap

The runner verified baseline failure but kept the resulting errors outside model
input. The frozen task goal described the dependency upgrade and desired HTTP
behavior, without the actual missing-method errors. That is an input limitation,
not an environment failure and not proof that error feedback will solve it.

A new preparation-only flag `--baseline-feedback` binds policy `case-errors-v1`
into the manifest. After matching the baseline, it extracts bounded case names,
pass booleans and failed error types/messages. It omits tracebacks, gold data and
replacement hints; labels the content untrusted; writes/hashes the supplied
observation artifact; and appends observations to the task input for either
strategy. Normal input-byte/model budgets still apply. Missing/malformed output
or a combined observation over 3KB rejects feedback rather than silently dropping
cases. Long fields are bounded and long error messages explicitly marked.

This is observed pre-edit baseline feedback, **not** automatic repair retry or
feedback from a previous candidate patch. Old frozen preparations default to no
feedback; execution cannot turn the flag on after freezing. Enabling it changes
model input and must be disclosed in comparisons; both arms need equal evidence.

Five runner tests pass, including freezing, no calls during preparation, bounded
observations without traceback/reference hints, acceptance and source-drift
checks. No new paid run has been prepared or executed for this feedback change.
Do not record the existing failed patch as repaired by these host tests.

## Executed baseline-feedback follow-up

The user subsequently executed `httpx-1588-localized-errors-v1`: three model
calls, 5,084 tokens, 18 tool calls and 23.906 seconds. It modified only the default
transport. This remains a failed development run, with all four cases failing.
The input baseline observation artifact is hashed in the result.

The new patch changes `request` to `handle_request` and `arequest` to
`handle_async_request`. It leaves `ext=extensions` unchanged. Consequently the
observed failure changes from missing-interface AttributeError to unexpected
keyword `ext` TypeError for sync and async cases. This supports partial repair
of the original reported interface, not an acceptance improvement or resolved
task. It does not establish that error feedback is generally beneficial; sampled
file choices differ and this is one repeatedly inspected development case.

The previous no-feedback candidate changed the keyword but not the method; this
candidate changes the method but not the keyword. Do not manually combine these
patches, inject the gold diff or count a hand-composed patch as model success.
Other compatibility errors may remain after these two changes.

Offline analysis: `.keel/localized-errors-trial-analysis-v1.json`, zero new model
calls. The one-shot path has no response to its own verifier errors. The next
design question is an opt-in bounded verify/repair loop using the same candidate
workspace and global budget. That is a substantive extension from one-shot
proposal execution and must have independent tests for budget sharing, bounded
attempts, source freshness, scope/audit preservation and failure retention before
paid execution. Do not repeatedly restart fresh-budget attempts on this case.
