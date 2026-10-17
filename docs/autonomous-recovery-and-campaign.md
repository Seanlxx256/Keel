# Autonomous recovery and environment campaigns

## Runtime recovery

Opt in with `"recovery": {"max_actions": 6, "repeat_limit": 2}` in an agent/proposal/localized-proposal config. This controller shares its action counter across localization protocol correction, proposal validation correction, evidence reselection and verification repair. It does not reset model, token, tool or wall-clock budgets. Tool-loop agent mode reopens an Implementer session after failed verification with observed output and the original declared files; it retains its existing per-turn protocol/tool feedback. Evidence reselection and proposal correction apply to proposal modes. The additional [adaptive strategy](adaptive-role-replanning.md) enables Critic routing and actual Scout/Planner cycles, with explicit host-authorized write roots and revised-plan approval. The automatic campaign enables that strategy by default.

The host routes typed failures to bounded actions; the model chooses definitions and edits from observed evidence. This is an observe/action/verify loop, not unrestricted self-reflection or arbitrary shell access. Decisions and failure fingerprints appear in the ledger, trace and result's `recovery` field. Repeated identical failures with unchanged evidence stop. Transport/authentication failures, policy/audit violations and exhausted execution budgets remain terminal.

Input capacity is distinct from an exhausted execution budget. Oversized patch inputs can trigger model selection of fewer complete current definitions within the original write scope. File/symbol catalogs are paged, with explicit model ranking and retained IDs across pages. Every page consumes the shared model budget. A single definition, goal, dependency payload or catalog item that cannot fit may still stop the run; the controller never silently truncates source or raises the cap.

Intermediate JUnit failures supply repair evidence while test deletion, missing reports and increased skips remain blocked. Each verification round writes a fresh report directory. Final validation still requires passing tests and audit.

## Automatic task and environment factory

`examples/run_autonomous_campaign.py` supports this sequence without per-PR scripts:

1. Discover bounded public Python repositories through GitHub search, excluding repositories in the existing development registry, or use explicit repositories. This is a bounded search page, not representative or exhaustive sampling; explicit repository overrides can include development data.
2. Collect merged compatibility PRs, receipts and exact first-parent/gold snapshots through the existing collector.
3. Freeze upstream gold test directories on both snapshots, preserving base-only tests/fixtures in the identical union on both sides. Base test configuration is used on both sides. No generated assertions or acceptance modifications are permitted during environment retries.
4. Ask the environment planner for Python and exact dependency pins; generate a fixed Dockerfile on the host. No model-provided shell commands, Dockerfiles, URLs or OS packages execute. Only requirements enter the build context; model/GitHub credentials do not.
5. Build old/new dependency images, verify installed pins, observe errors and replan for at most three attempts. Duplicate recipes stop. Images are recorded by immutable ID.
6. Require base-old pass, base-new fail, gold-new pass, identical nonempty JUnit identities and zero skips before invoking Keel. Run all frozen top-level test directories, not a model-selected subset.
7. Run Keel on a separate base workspace with frozen tests, new image and observed failure output. Gold source/commit and changed-source file lists are excluded from solver input. Verify test hashes afterward and retain every failure.

The first supported scope is Python/pytest with top-level `tests`, `test` or `testing` directories, regression-test changes, PyPI dependencies and no external services. Native libraries, system packages, editable installs, complex build systems and service/database provisioning are not automated yet. Unsupported candidates are logged and the campaign continues; this does not establish that their bugs are unsolvable. Tests are copied into container tmpfs and run offline with the normal verifier restrictions; large repositories can exceed that tmpfs limit.

A campaign has 30 model calls, 300,000 charged tokens, 100 tool operations and 1,800 seconds by default, shared across environment planning and solver runs. GitHub client internal bounded HTTP retries and Docker internal build work are not individual tool-counter entries. Exact token usage is provider reported when available; byte estimates remain conservative admission checks. Full build logs, recipes, test executions and model responses are retained. A completed campaign can have zero successful tasks: consult `counts` and individual statuses.

Plan without network or model calls:

```powershell
python examples/run_autonomous_campaign.py --model-config .keel/model-openai.json --output .keel/autonomous-campaigns/python-first --repository-limit 1 --candidates-per-repo 1
```

Run the entire campaign (Docker, network and metered model calls):

```powershell
python examples/run_autonomous_campaign.py --model-config .keel/model-openai.json --output .keel/autonomous-campaigns/python-first --repository-limit 1 --candidates-per-repo 1 --execute
```

`GITHUB_TOKEN` and the model config's credential environment variable must be set in the launching terminal. Output directories are exclusive; choose a fresh directory for another campaign. Docker images remain cached; the campaign never removes unrelated containers or images.

For an existing frozen package, prepare with `--recovery-actions 6 --repair-attempts 3`, then execute the prepared output normally. Existing prepared outputs are not silently amended after code changes.

## Evidence and boundaries

Offline regression tests exercise recovery decisions, shared-budget exhaustion, report freshness, scope checks, catalog paging, environment-plan validation, observed build failure/replanning and transition gates. The plan-only CLI has been exercised. The new generic factory has not yet completed a live GitHub/Docker/model campaign in this environment. It is an experimental implementation, not proven fully automatic provisioning for arbitrary repositories.

Results remain `benchmark_ready: false`. Selecting tests from a PR and using a reconstructed environment does not prove representative sampling, sufficient regression coverage or absence of contamination. Models may already know public fixes. The factory does not edit Keel's own code, merge changes or claim to improve its own algorithm. Automated runtime-source proposals would require a separate regression suite and evaluation gate before adoption.

Design references: [SWE-bench harness](https://www.swebench.com/SWE-bench/reference/harness/) separates reproducible container execution from patch grading; [SWE-ReX Docker deployment](https://swe-rex.com/latest/api/deployments/docker/) provides an established container-runtime integration reference. These are design references, not imported integrations or reproduction claims.
