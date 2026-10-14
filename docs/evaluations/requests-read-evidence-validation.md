# Requests evidence-reading validation

On 2026-10-14, the final diagnostic run at
`.keel/swe-public/96e21fe1ccfd407b976c43bb14b16d08/` evaluated
`psf__requests-1724` at commit `1ba83c47ce7b177efe90d5f51f7760680f72eda0`.
The existing semantic index was reused. It used code-aware ranking, a 100-line
budget, one repetition, read evidence policy, 8K chat context, and unchanged
per-run limits (300 seconds, 30,000 tokens, four model calls, 100 tool calls).

## Changes

- T2 receives metadata for up to the visible-node limit and must read selected
  symbols. Unread selections and reads outside code bounds are rejected locally.
- Read pages contain 1,000 characters. Per-turn state retains the original issue,
  current catalog, actual read pages and action trace. The final turn narrows the
  catalog to read IDs. Persistent events retain model replies and observations.
- Query/expand actions are disabled when the node budget is full, avoiding
  repeated actions that cannot add candidates.
- Code-aware ranking prioritizes candidate ranges containing explicit
  `file.py:line` references from the issue. For this issue, `sessions.py:313`
  promotes `Session.request`. No gold labels or instance-specific rules are used.
- The runner explicitly configures 8K chat context and a compute batch of 32.
  Query embedding and configured chat requests release their models afterward.

## Measured result

| Mode | Completed | Line recall | Model calls |
| --- | --- | --- | --- |
| T0 | Yes | 0 | 0 |
| T1 | Yes | 0.04621 | 0 |
| T2 | Yes | 0.02310 | 2 |
| Adaptive | Yes | 0.02310 | 2 |

T2 and adaptive each issued a read of `Session.request`, then explicitly selected
the same symbol. The reader guard checked the selected ID against actual reads.
This is a two-call read/selection trajectory, whereas the preceding passing
Requests run selected a candidate directly and had zero core-line recall.
T2 still underperforms T1 on this instance; a read is necessary evidence access,
not proof that the model understood the code or isolated the faulty line.

The run completed in approximately 69 seconds with `all_passed=true`.
[Compact evidence](requests-read-evidence-validation.json) retains the source hash,
summary and model replies. Gold regions include broad file ranges, so positive
line recall alone does not demonstrate precise edit localization. The emitted
symbol prefix need not include the exact reported line.

## Diagnostic attempts and limitations

Earlier preview-based and intermediate read-based attempts remain in separate
artifact directories. Initial read mode exposed no-op expansion and excessive
conversation growth. Explicit chat context made the model input larger and
increased actual usage; bounded decision state restored completion within the
original budget. Low earlier input usage suggested context loss but did not prove
the precise truncation behavior. The final context size is explicit and recorded.

Git failures were independently diagnosed as `fatal: not enough memory for
initialization`. Model unloading reduced residency. Git HEAD and untracked-file
queries now retry exit 128 once; repeated errors fail closed, retaining the reason
when HEAD cannot be read. No dirty or mismatched snapshot is accepted as a result
of a failed command. Persistent failures are not counted as successful runs.

This is one development instance with one repetition and multiple simultaneous
policy changes. It supports neither causal attribution nor benchmark-wide claims.
The old 72-run baseline and Requests repair runs remain separate. Next validation
should repeat the final policy across all three repositories and then use held-out
instances; quality and model-call cost both need comparison. RRF remains the
default ranking policy, and official evaluator parity is unverified.
