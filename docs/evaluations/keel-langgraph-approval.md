# Guarded same-process LangGraph approval

## Contract

`approval_before_write: true` requires LangGraph and an explicit host callback.
The callback receives a validated plan digest, source snapshot digest, declared
files, ledger reference and current budget and returns a strict boolean. It is
not a model tool. The CLI exposes `--interactive-approval`; input must be APPROVE,
and EOF denies. Approval grants no additional file or command permissions.

The graph pauses in a separate approval node after successful Planner validation
and before any Implementer work. No effects occur before interrupt inside this
node because LangGraph reruns its interrupted node on Command(resume=...). The
host process retains the original runtime objects. The resumed approval node
checks budget, plan/config digests, full workspace bytes and existing write policy
before routing onward. Rejection, bad input, changed source/plan or exhausted
budget routes to Critic with failure artifacts. Prior graph stages and budget
charges are not replayed. Audit and independent acceptance remain unchanged.

The original wall clock includes human wait. Host callback/input is blocking and
not forcibly interrupted on expiry; the resumed guard rejects an expired budget.
The filesystem matching check is not an OS lock against changes after validation.
Concurrent runs, crash restoration, generic time travel and arbitrary checkpoint
replay are unsupported. `orchestration.resumable: false` continues to mean no
cross-process recovery; `resume_scope` labels same-process approval support.

Official behavior consulted:
https://docs.langchain.com/oss/python/langgraph/interrupts

## Verification (2026-10-15)

Real LangGraph 1.2.15 and langgraph-checkpoint-sqlite 3.1.2 in the user's installed
virtual environment passed all 13 orchestration tests, with zero skips. Coverage
includes:

- Native parity, checkpoints, model sessions, ledger sharing and one-time Critic.
- Pause before writes; resume without repeating plan, item or command execution.
- Explicit denial and non-boolean responses refuse writes.
- Plan/config or source changes invalidate the approved decision.
- Prior tool charges remain spent after resume; expired waiting budget refuses work.
- Agent model-call/token counts remain 3/30 at approval and 6/60 at completion.
- Approval requires an explicit trusted callback before artifact creation.

A real model-free approval/resume demo passed, with one interrupt and eight
checkpoints, preserving the pre-approval tool charge (1) through final total (4).
Artifacts: `.keel/approval-demo/7a36b46c48534ac294ec427c23973cd6`.
This is not a live Ollama experiment or Docker isolation test.

The base-interpreter full regression completed 228 tests with 15 optional skips
and no failures before the final model-budget test addition. The final installed-
framework targeted suite passed all 13 tests afterward. CLI help and whitespace
checks passed.

## Usage

```powershell
python examples/langgraph_approval_demo.py
python -m unittest discover -s tests -p test_orchestration.py -v
```

The demonstration uses a persistent disposable repository under
`.keel/approval-demo/<id>`, local Python acceptance, and no model. Programmatic
`--decision approve` and `--decision deny` modes test host policy responses;
interactive mode is the default. Denied runs return nonzero and retain evidence.

Next persistence work must define sealed run/config/source identity, durable
budget/deadline restoration, exclusive ownership and idempotent side-effect
boundaries before any cross-process resume is exposed. These are not provided
merely by adding a checkpointer.
