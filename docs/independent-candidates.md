# Policy-bound candidate discovery

## V3: explicit dependency/version metadata evidence

After closing the unsuccessful v2 cohort, a separate discovery plan is stored
in `examples/independent_candidate_policy_v3.json`. It searches four project/
dependency pairs: Requests/urllib3, HTTPX/httpcore, pytest/pluggy and Rich/pygments.
This is another deliberately chosen Python convenience sample, not an unbiased
sample of dependency upgrades. Seed, repository count and other bounds are
recorded before collection; the v2 results remain unchanged.

The change is grounded in primary maintenance records rather than selecting a
known successful agent task: e.g. HTTPX's
[HTTPcore 1.0 discussion](https://github.com/encode/httpx/pull/2885) identifies a
specific dependency transition but also warns about optional async dependencies.
That PR is not manually inserted into the selection, and no claim is made that
it contains a suitable source repair or reproducible base failure.

V3 searches dependency names in merged PR titles. On each collected candidate,
a uniform extractor inspects public title/body text for an explicit version
adjacent to that dependency name. It records a bounded excerpt, originating
field and extraction method with `verified_transition: false`. Mentions of a
different Python version elsewhere in the sentence do not qualify. Candidates
without this evidence remain in screening records with an exclusion reason.
These snippets are untrusted curator metadata, not instructions or model input.
Missing commits retain the v2 exclusion/counting behavior. Limits and seeded
ranking are unchanged in mechanism; v3 has its own configured seed and pool.

```powershell
python examples/prepare_independent_candidates.py --policy examples/independent_candidate_policy_v3.json --execute
```

No Docker or inference is run. This starts a new search, not cached continuation
of v2's different query. Preserve the original pool and all unsuccessful trials.
If the bounded pool is insufficient, report that result without silently
enlarging it. A version mention alone does not establish removed APIs, affected
behavior, supported environment or an actual upgrade defect. Source review and
base-fail/reference-pass remain required before freezing executable tasks.
V3 collection completed and selected pytest #11856, HTTPX #1588 and Requests
#6757. [The cohort review and HTTPX dependency contrast](evaluations/independent-cohort-v3-review.md)
records current evidence and remaining validity checks. No independent model
evaluation or executable task readiness has been established.

## First v2 shortlist and source curation

Collection `.keel/independent-candidates/b1faa17118f54ef29d51ef40d24705fb`
completed all six repository collections. Its fixed selection is Click #9,
pytest #7832 and Requests #4204. These are metadata candidates only: the title
of Requests #4204 explicitly concerns a comment; pytest #7832 removes an old
compatibility shim; Click #9 concerns Windows behavior. This exposes weak
precision of keyword discovery, not three evaluation-ready upgrade repairs.
Do not replace them with more attractive PRs after inspection.

Uniform source curation (no model, Docker or project code execution):

```powershell
python examples/review_independent_candidates.py --collection .keel/independent-candidates/b1faa17118f54ef29d51ef40d24705fb --execute
```

It verifies the shortlist against the original policy/collection, fetches pinned
clean Git snapshots, verifies the merge first parent and checks actual changed
source paths against metadata. AST comparison uses Python's encoding-aware
parser, includes type comments and preserves docstring differences. Ordinary
comments/formatting do not establish an AST change. Added/deleted sources remain
changes; unparseable legacy code is explicitly unsupported, never silently
accepted. No candidate IDs are dropped or substituted in `review.json`.

The rule `python-ast-change-required-v1` is recorded before source review. An
AST-equivalent source diff is excluded under this screening rule; this does not
prove semantic equivalence (tracebacks, source introspection and line metadata
can differ). Changed ASTs remain `needs_environment_reproduction`, not ready.
Platform requirements, dependency-change relevance, an independent acceptance
probe and base-fail/gold-pass still require curator checks. A Windows bug must
not be claimed reproduced by an unrelated Linux test. Baseline-green maintenance
cleanup must not be reworded into a contrived failure to manufacture a repair.

Preparation without downloads succeeded at
`.keel/candidate-review/1abf27ebe3fe468fbd6503675dd1649a`. User-side source review
then completed. Requests was AST-equivalent; curator inspection identified
platform-only Click changes and unsupported-version cleanup in pytest.
[The cohort disposition](evaluations/independent-cohort-v2-curation.md) retains
all three candidates and records that no executable upgrade task was established.
There were no model evaluations. A revised discovery experiment must be separately
versioned rather than silently substituting candidates in this cohort.

## Explicit v2 amendment: unavailable merge commits

The v1 pool remains incomplete. A user-side direct request confirmed GitHub's
response for Pillow #1365: no commit found for merge SHA
`1f7a9cae19fb7547165eefccb61e618988151551`. This establishes API object
unavailability at collection time, not why it disappeared or whether some Git
mirror could still contain it. No parent revision may be invented.

`examples/independent_candidate_policy_v2.json` explicitly amends only the
missing-commit rule. Across all repositories, a 404/422 on the immutable commit
endpoint is treated as `merge_commit_unavailable` only when the API explicitly
reports no commit found. The sanitized typed error is hash-receipted and can be
replayed offline. That PR stays in collection/screening records as excluded,
with no verified parent. It counts toward the existing per-repository limit;
there is no extra fetch quota or replacement PR to compensate. Other HTTP and
transport failures still block complete collection. The original strict
collector behavior and v1 policy remain available.

Run a new v2 collection using the original archived listing/responses:

```powershell
python examples/prepare_independent_candidates.py --policy examples/independent_candidate_policy_v2.json --cache-from .keel/independent-candidates/f02d9dc4d74b4c679a5ff722b8567ad8
```

This is a new discovery experiment, not a successful resume of v1. Its plan
records the prior plan and implementation hashes. Cache reuse requires identical
repositories, query, bounds, seed, selection count and other policy fields;
only the explicit version/missing-commit amendment may differ. Hash-verified
cached responses are reused and missing routes may use network. No model or
Docker execution occurs, and no new selection success is claimed before this
command completes. Do not delete or relabel the v1 incomplete result.

This is the next step toward independent evaluation, not an independent score.
The three development cases and their repositories remain excluded. Current
independent executable tasks: zero.

## Predeclared discovery policy

`examples/independent_candidate_policy.json` fixes six repositories (Requests,
HTTPX, Click, pytest, Rich and Pillow), a merged-PR title query `compatibility`,
one page and at most five collected source-changing candidates per repository,
seed 20261015 and a target of three repositories with one candidate each.
This repository pool is a deliberate convenience sample of Python projects,
not a representative or uniform sample of GitHub maintenance work.

The collector resolves repository identities, archives hash-receipted API
responses, checks complete PR file lists and merge first-parent metadata, and
records non-source skips. Metadata screening keeps merged compatibility-title
PRs with one to three non-test Python source changes and pinned revisions;
CI/developer-tooling candidates and non-Python source changes are excluded.
Dependency manifest changes are not mandatory: these are compatibility
candidates, not yet confirmed dependency-upgrade tasks.

Per-repository candidates are ranked by SHA-256(seed:repository:PR); repository
winners are ranked by SHA-256(seed:repository). Selection uses no model outcome.
All candidate reasons and collection errors remain visible. Incomplete
collection or insufficient eligible repositories yields an empty selected list,
not a survivor-only experiment. API updated-order search and bounded collection
still introduce sampling bias; seeded ranking does not remove it.

Do not manually adjust filters because a chosen candidate fails reproduction or
model repair. Keep it in the planned cohort and report exclusions or failures.
There is no automatic reserve promotion. If a new discovery policy is needed,
label it a new experiment and preserve the original pool and plan.

## Commands

Prepare a local policy record without network or model access:

```powershell
python examples/prepare_independent_candidates.py
```

Collect public GitHub metadata (no Docker or model calls):

```powershell
python examples/prepare_independent_candidates.py --execute
```

The existing optional `GITHUB_TOKEN` environment variable is used by the
read-only collector; never paste its value into chat. GitHub API limits and
network failures can leave partial collections. Every planned repository remains
in `collections.json`; `shortlist.json` reports incomplete/insufficient status.

Output under `.keel/independent-candidates/<id>`:

- `plan.json`: policy, policy hash, development registry hash and collector/
  selector/runner hashes, saved before requests.
- `repositories/<owner--repo>/responses` and `receipts.json`: raw metadata
  responses and hashes. They are curator-only and may contain PR patches; never
  pass this folder to the agent as context.
- `collections.json`: all planned repositories, candidates, skips and errors.
- `shortlist.json`: reasons, deterministic ranking and selected metadata entries.

Replay archived responses without network:

```powershell
python examples/prepare_independent_candidates.py --replay-from PREVIOUS_DIRECTORY
```

Resume a partial collection, reusing verified responses and requesting only
missing routes:

```powershell
python examples/prepare_independent_candidates.py --resume-from PREVIOUS_DIRECTORY
```

Resume requires unchanged policy, development registry, collector and selector.
Runner changes are explicitly recorded in `plan.json` with the prior plan hash;
this permits adding transport diagnostics without changing selection rules.
Existing lists and responses are reused even if current API listings differ.
No HTTP 422 retry loop is added. If a missing route still fails, that repository
remains failed and selection remains empty. Terminal output now includes each
repository's count/error and failed request route, not only an incomplete flag.

First live pool `.keel/independent-candidates/0fd939ad4c664faab28d49fc2c8aed45`:
five repositories completed; Pillow collected two candidates then returned HTTP
422. Last cached PR was #1365, followed by its file list; the next expected route
was `/repos/python-pillow/pillow/commits/1f7a9cae19fb7547165eefccb61e618988151551`.
The original runner did not record its failed route, so this endpoint is inferred
from collector order, not confirmed by a saved failing request. The exact HTTP
cause remains unconfirmed. No repository is dropped or candidate substituted.

Replay requires matching policy, registry and collector/selection code hashes,
valid receipt hashes and every requested route in cache. It never falls back to
network. A partial cache may remain incomplete; this is visible, not silently
repaired with a new current listing.

## Task preparation boundary

Shortlisted PR metadata must next undergo curator environment/reproduction
review. Do not write per-case model hints. The declared future localization
policy uses base-failure traceback paths and uniform source-window construction;
PR gold file lists are screening metadata, not model-provided localization.
If this localization cannot prepare a task, record the exclusion rather than
inserting hand-selected anchors after observing a repair failure.

Before model execution, freeze complete source/acceptance/environment packages,
settings and implementation using the [evaluation protocol](evaluation-protocol.md).
The existing freeze hashes declared files only, so packages must explicitly bind
all referenced resources. Task validity and operator exposure require review;
neither is inferred from a shortlist. There is no independent execution adapter
yet. All discovery outputs remain `benchmark_ready: false` and
`independent_tasks_ready: 0`.

Four new tests cover outcome/order-independent ranking, incomplete/insufficient
pools, visible exclusions/development aliases and real collector contracts with
hash-receipted offline replay using mocked public responses. No live discovery
or model quality claim follows from these tests.
