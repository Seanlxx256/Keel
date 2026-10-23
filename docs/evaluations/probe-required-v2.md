# Required probe v2: execution attempted, import failed, repair blocked

Evidence: `.keel/repair-review/probe-required-v2/results/report.json`, per-arm
model-transcript.jsonl and ledger.sqlite. Original results preserved unchanged.

Two calls /13,096 recorded tokens /27.235 seconds /one tool execution. This is
not the earlier empty-code failure. First reply supplied executable Python and
Docker executed it against the mounted candidate file. stdout confirmed exists,
str-first and fallback source markers. Child returncode=1: importlib loaded the
file as mounted_card, so `from . import conf` raised ImportError: attempted relative
import with no known parent package. Wrapper/container returncode=0 does not mean
the child experiment succeeded; its nested probe.returncode=1 is authoritative.
No float-format output or discriminating causal observation was obtained.

Second reply proposed another probe, trying to manufacture package modules. It
was rejected before execution because the experiment allowed one probe only.
The proposed revision is not certified correct: it still uses a top-level spec
name, and the mounted snapshot contains only selected files, not a full package.
Do not claim self-repair succeeded or would have succeeded with another attempt.

The run stops incomplete/PolicyDenied, not time/call exhaustion. Source unchanged;
no acceptance. Required policy improved action selection on this example, but
useful experiment and diagnostic-quality criteria remain unmet. Frozen micro
constraints deliberately permitted only one probe, which blocked correcting a
failed experiment even though one model-call slot remained.

## Corrective judgment

Stop the promised wording-retry line; no next paid run or new prompt change this
turn. The old 30-minute tests were upper-bounded agent/verification loops, not
30 minutes of successful causal experimentation; earlier proposal mode had no
probe tool. They do not prove this capability was previously functioning.

Next engineering work should inspect execution context rather than add supervision:
provide a generic candidate package context matching the verified environment,
separate child/script failure from useful observation, and consider a finite
same-budget correction for failed probes. Validate those execution mechanics with
representative package-import fixtures and independent ground truth before buying
another case run. Do not bake this task's function, inputs or repair into helpers.
