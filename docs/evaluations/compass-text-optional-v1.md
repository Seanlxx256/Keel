# Optional Compass text search: first paired pilot

Frozen plan: `.keel/swebench/compass-text-optional-v1/plan.json`.
Results: `comparison.json` in the same directory. Three tasks were planned;
two completed both arms. Local exploration remained enabled in both arms.
The external arm offered optional Scout-only docs/config search, not required use.

| Task | Local tokens | Optional tokens | Official result, both arms | External calls |
|---|---:|---:|---|---:|
| pydata__xarray-4356 | 66,656 | 35,220 | passed | 0 |
| pytest-dev__pytest-7982 | 11,919 | 13,175 | passed | 0 |
| matplotlib__matplotlib-25775 | not run | not run | reference timeout | not run |

Paired totals: 78,575 versus 48,395 tokens; 25 versus 18 model calls;
1,058.796 versus 756.766 agent seconds. These are observed run differences,
not demonstrated benefits from Compass: neither optional arm invoked it.
There is no demonstrated repair-success improvement or statistical claim.

The Matplotlib reference harness exceeded its 1,800-second launcher deadline.
Its log reports successful environment-image construction before instance
execution. The exact remaining delay is unverified; do not classify it as a
source repair failure or silently replace the task. Completed pairs are retained.

Scout ledger decisions show local list/search actions targeting the supplied
error string or `follow_symlinks=False`. Both initial replies violated the
action envelope and were corrected by the host. Neither model explicitly
explained a decision to avoid docs/config search. Inferring that these tasks
did not require text search is plausible, not a verified tool-choice diagnosis.

Configuration and the runtime code path include authorized MCP tools in the
Scout prompt. This run did not persist the actual catalog separately, so exact
historical catalog visibility cannot be independently replayed from its trace.
Future runs emit `agent_tool_catalog` with tool names and required-use policy;
no credentials or source content are included. This telemetry change requires
a new frozen plan, not rerunning this plan against changed implementation hashes.

Next: audit tool visibility in a newly frozen trial, retain zero-call outcomes,
and test task relevance without forcing calls or selecting tasks after results.
Diagnose the reference timeout separately before authorizing a recorded retry.

## Reference timeout diagnosis

Internal logs show environment-image build took about 930 seconds. Instance
setup then installed system dependencies including TeX, fonts and image tools.
At 20:03:21 it began building the editable Matplotlib wheel; the 1,800-second
launcher deadline then expired. No test execution is recorded. This supports
build-time exhaustion, not a demonstrated dependency incompatibility or test
failure. Completion with a longer deadline remains unverified.

The generic bridge now exposes `--timeout` and records `timeout_seconds`.
Its default remains 1,800 seconds. A separate retry may use 3,600 seconds with
unchanged task/reference inputs, retaining the first outcome. Such a retry is
additional infrastructure validation, not a first-attempt paired score; it does
not authorize rewriting this closed comparison or bypassing frozen hashes.
