# Flask-Login historical issue task: first model trial

Successful reproduction `.keel/upgradebench-reproduction/5db1ee314bcb4cfabda29fbc6b075a45` confirms all five cases pass at base-old, all five fail on the expected removed import at base-new, and all five pass at official gold-new. The historical range spans 12 commits and is not PR 813's adjacent first-parent pair. Earlier failed experiments remain unchanged.

Package `.keel/task-packages/flask-login-issue5279-v1` exports a deliberately restricted task JSON containing only base revision, general behavior requirements, repository identity and source scope. It excludes official gold, intermediate commits, curator changed-file list, issue body and solution rationale. The verifier retains the same five-case probe, resolved new image ID and exact dependency versions. Source inventory and evidence hashes are frozen. Baseline checks require the expected ImportError message, not merely an unrelated import failure.

First trial `.keel/transition-trials/flask-login-issue5279-first` uses 24,000 input bytes, the existing 450-second/30-model/60-tool/180,000-token shared budget, up to two verification repairs, and observed baseline source frames. It starts from the historical old snapshot. Task scope is existing Python files under src/flask_login/, with final changed-path checks; post-plan runtime write scope remains the model's audited declaration. No official repair snippets enter inference. Ten package/runner/grid regression tests passed; no model requests occurred during preparation.

```powershell
python examples/run_transition_task.py --output .keel/transition-trials/flask-login-issue5279-first --execute
```

This is a curated historical task, not independent benchmark coverage. Source and acceptance were designed after curator inspection, and Flask-Login's failure history is known. A future pass demonstrates these five behaviors only, not full upstream test coverage or production authentication security. Preserve first attempt results; further outcome-driven runtime changes make subsequent runs development diagnostics.
