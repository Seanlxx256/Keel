# Context cap experiment

Compare 12,000, 24,000 and 48,000 input bytes on the existing HTTPX development task. These are decimal byte caps, not token counts. Only `agent.max_context_bytes` varies: model configuration, implementation, task, evidence policy, acceptance commands and per-run budgets are frozen and checked before execution.

Start with one run per cap. The seeded order reduces a fixed execution-order bias; it does not seed provider output or make generations deterministic. Three runs still represent one known development task and zero held-out tasks. A pass cannot establish generalization or a statistically reliable advantage.

```powershell
python examples/run_transition_grid.py --package .keel/task-packages/httpx-1588-v1 --model-config .keel/model-openai.json --caps 12000 24000 48000 --repeats 1 --seed 42 --output .keel/transition-grids/httpx-context-v1
python examples/run_transition_grid.py --output .keel/transition-grids/httpx-context-v1 --execute
```

Preparation makes no model requests. Execution normally reaches four model calls per arm (12 total) if all stages are reached; early failures use fewer. Each arm retains the existing limits of 30 model calls, 180,000 tokens and 450 runtime seconds, with a separate baseline probe. Running three arms multiplies the possible expense. Execution refuses an already started grid rather than silently rerunning it.

`results.json` and `results.md` retain every arm, including failures, and report acceptance, changed files, failure stage, model calls, tokens, elapsed time including baseline, and maximum actual model input bytes. Increasing a cap permits more evidence but does not force the model to use it or guarantee a better patch. Compare actual inputs and cost alongside acceptance.

Keep historical 12 KB failures and separately prepared 24 KB trials outside this matrix: their implementation or generated evidence can differ. Use the newly frozen grid instead of an older single-run preparation. After this screen, repeat promising settings and test additional frozen tasks before claiming an improvement. Do not treat repetitions as additional task coverage.
