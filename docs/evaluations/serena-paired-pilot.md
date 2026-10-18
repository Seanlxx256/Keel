# Serena paired exploratory pilot

Protocol: freeze three previously unlisted task IDs from the local SWE-bench Verified
dataset using the existing deterministic selector and exposure receipts. Use three
distinct repositories, preserve selected IDs when preflights or repairs fail, and
make no held-out/representativeness claim. Model, implementation, dataset, task and
reference receipts are bound by the existing batch plan. The tool profile, executable
and absolute file arguments (including its generated launcher) are also hashed.
Installed server dependencies, remote services and model-provider internals are not
fully frozen by these hashes.

Both arms use the same six-turn initial local exploration, capped recovery exploration,
30 model calls, 80 tool calls, 180000 tokens and 1800 agent seconds. The local arm has
no MCP tools; the MCP arm adds the operator-reviewed profile and requires one attempt
before local fallback. This compares a tool-enabled selection policy against matched
local exploration, not the isolated causal effect of Serena. No Compass provider or
experience memory is added. Native tools and error recovery are otherwise identical.

One official reference preflight gates both arms per task. Execution order alternates
by task. Each arm receives a separate checkout, ledger and final official grading.
Results preserve all failures, budgets, verification rounds and tool request outcomes.
Paired rates include only tasks with two completed grading results; missing/error arms
and reference failures remain explicit alongside the planned denominator. No rerun or
task replacement is performed automatically. Three pairs with one sample each cannot
establish statistical significance. Freeze drift stops execution.

Prepare with examples/run_swebench_tool_comparison.py supplying dataset, model config,
harness Python, authorized MCP config and fresh output. Execute that frozen output
with only --output and --execute. The execution marker refuses accidental reruns;
an interrupted attempt remains archived and requires an explicit new experiment.
Reference preflight/official grading overhead is outside the per-agent budget.

## Pilot v1 results

Frozen plan: 5d3e228716f811e65cf2b2c4af9641591757ccdecf7fc89a4169b3323741baef.
Plan, implementation, inputs and tool files were reverified after completion.
Artifacts: .keel/swebench/serena-paired-pilot-v1/comparison.json.

| Task | Local | Required MCP | Local tokens | MCP tokens |
| --- | --- | --- | ---: | ---: |
| pydata__xarray-4075 | Official pass, 1 verification | Official pass, 1 verification | 33145 | 11281 |
| pytest-dev__pytest-6202 | Official pass, 1 verification | Official pass, 1 verification | 18137 | 15913 |
| matplotlib__matplotlib-25122 | Not executed | Not executed | — | — |

Both completed MCP arms made one successful Serena get_symbols_overview request.
Ledger payloads contain actual Weighted-related symbols for Xarray and collection/
parametrization symbols for Pytest. All four final grading receipts show
patch_successfully_applied=true, official_resolved=true and no infra_failure.

Among the two complete pairs, both policies passed 2/2, all at first verification.
Summed agent-accounted costs:

| Metric | Local | Required MCP | Observed reduction |
| --- | ---: | ---: | ---: |
| Tokens | 51282 | 27194 | 46.97% |
| Model calls | 15 | 9 | 40.00% |
| Tool calls | 26 | 16 | 38.46% |
| Agent seconds | 456.844 | 437.202 | 4.30% |

Time is mixed per task: Xarray 292.953 -> 264.609 seconds; Pytest 163.891 ->
172.593 seconds. These clocks include internal acceptance overhead but exclude
reference preflight and final official grading. Token totals are reported usage,
not billed currency. No success-rate gain or statistically stable cost gain is proven.

Matplotlib's reference-only grading failed before repair: instance setup_repo.sh
returned code 100 because apt could not fetch packages from archive.ubuntu.com:80
(log destination IP 198.18.0.72). This establishes a network reachability failure at
package download, not its underlying proxy/DNS cause. The original failure remains
archived; no replacement task was selected. It is an infrastructure-blocked pair,
not two model repair failures. Thus 2/3 planned tasks were runnable, not 3/3 passes.

Next: restore container package-source connectivity and reproduce the same selected
Matplotlib reference preflight before scheduling either arm under unchanged conditions.
Any retried result must be separately recorded; retain original blocked denominator.
