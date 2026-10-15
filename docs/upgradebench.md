# UpgradeBench candidate intake (W9, initial stage)

## Status

The code imports and screens PR metadata. It does not yet build evaluation-ready
tasks, check out repositories, build Docker images, execute baseline/gold tests,
or establish resolve-rate denominators. All outputs explicitly set
benchmark_ready=false, and ready_tasks remains zero.

## Files and commands

- `examples/mine_upgradebench.py`: bounded read-only GitHub REST collection.
- `keel/upgradebench.py`: schema checks, heuristic filtering, frozen reports.
- `tests/test_upgradebench.py`: schema/filter/provenance/pagination tests.

```powershell
python examples/mine_upgradebench.py --repository psf/requests --limit 3 --pages 1
python -m keel.upgradebench --input D:/path/to/candidates.json
python -m unittest discover -s tests -p test_upgradebench.py -v
```

The input is a JSON array. Each object requires repository (owner/name), positive
integer number, string title, boolean merged, distinct full lowercase 40-character
base_commit/gold_commit, changed relative paths in files, and existing CI paths in
ci_paths. Malformed schemas, escaping paths, repeated files or duplicate PR IDs
fail the batch before publishing a screening directory. Existing output directories
are never overwritten. Metadata assertions in a local export are not authenticated.

## Collection and selection

Collection looks at at most three recent closed-PR pages (100 entries/page), and
imports at most 20 merged title-matching records. It is not exhaustive, random,
or representative. Title terms upgrade/bump/migrate are only candidate signals,
not proof of breaking changes. Each selected PR is fetched independently, as are
its file list, merged commit parents and merged tree CI paths. File lists above
300 files, count mismatches, duplicates and truncated trees fail collection.

Base means the first parent of the merged commit; gold means that merged commit.
This handles the evaluation boundary more carefully than using PR base.sha, but
rebases/merge policies and exact diff metadata must still be checked against Git.
The PR files endpoint may differ from the merged first-parent range; this remains
an explicit pending verification, not silently treated as a frozen gold diff.

Screening requires merged status, a title signal, >=3 changed files, dependency
manifest changes, non-test source changes and a recognized CI path. Language and
manifest heuristics are intentionally limited and documented in code; runtime-only
migrations, other languages and unconventional test layouts can be missed.
Rejected records retain all applicable rejection reasons. Each record retains
pending Git-range, description/leakage, Docker reproduction, base/gold test outcome
and test/environment validation checks. CI existence does not establish reproducibility.

A stable SHA-256 ranking over seed and canonical PR ID selects ceil(10% of eligible
candidates) for manual sampling. Selection is order-independent; review is pending,
not completed. Every task still needs a curated, non-leaking instruction before it
can be exposed to an agent. Sampling is not permission to skip that requirement.

## Data boundaries and reproducibility

The miner archives raw responses and byte hashes; screen output includes canonical
input/manifest hashes. Only public API URLs are constructed from a validated repo
identity and commit SHA. An optional GITHUB_TOKEN goes only in HTTP headers and is
not saved or printed. Error reports exclude response bodies and credentials.
Archives contain PR body, changed-path and gold-revision information and must stay
curator-only. No task prompt is generated from them automatically.

The miner does not accept build scripts or commands from PRs. Future test/image
configuration must be operator-reviewed. Gold code and gold tests must not leak
into agent-editable baseline source. Base/gold should run the same frozen acceptance
bundle under the same pinned environment. Baseline failures must be genuine task
failures, not package/download/collection errors; gold must pass. Test identities,
zero collection and skipped counts need separate checks.

## Evidence (2026-10-15)

Five tests passed: eligible-not-ready status, multiple rejection reasons,
malformed paths/revisions, deterministic manual sample/no-overwrite/duplicate
rejection, and first-parent pinning with incomplete-file/tree refusal.
A real GitHub collection attempt failed due to connection restrictions:
`.keel/upgradebench-mining/cb230a13dc964ab996a014005bd519fc`.
No real candidate count, validated task count, manual review completion or benchmark
score is claimed from that attempt or from synthetic test records.

Official API contracts consulted:

- https://docs.github.com/en/rest/pulls/pulls
- https://docs.github.com/en/rest/commits

## Next acceptance gate

### Exploratory compatibility review pool

Schema v3 retains strict screening unchanged and adds
`compatibility_review_candidate`. Compatibility/migration title signals with
non-test source changes, merged status and CI evidence may enter this pool even
without three changed files or a dependency manifest change. Only those two
structural reasons can be waived; tooling classifications remain excluded.
Waivers are recorded explicitly. These metadata heuristics do not establish an
external dependency migration or semantic correctness.

The independent queue requires review of every entry, not a 10% sample; the
existing strict-pool sample and counts retain their original meaning. Queues can
overlap and must never be added as independent task counts. Required evidence
includes dependency target pinning, semantic API changes and same-environment
base-fail/gold-pass execution. `benchmark_ready` remains false.

Real Starlette cache replay produced two review candidates (#1936 and #2400),
zero strictly eligible records and zero ready tasks. See the
[preliminary #1936 review](evaluations/upgradebench-starlette-1936-review.md).
Thirteen targeted tests pass, including exclusions for unmerged, missing CI,
test-only and tooling changes.

### Targeted discovery and online continuation

```powershell
python examples/mine_upgradebench.py --repository Kludex/starlette --discovery search --query compatibility --limit 10 --pages 2
```

Search mode uses the GitHub issues search endpoint with repository, merged-PR and
title qualifiers. Query choices are `migration`, `compatibility`, and `upgrade`;
Before searching it resolves `/repos/{owner}/{repo}` and uses the returned
canonical `full_name`, including repository transfers. Archived Starlette PR
responses identify `Kludex/starlette`; the old `encode/starlette` search produced
HTTP 422. That response alone does not conclusively establish its validation
cause, but canonical resolution avoids searching the stale name. HTTP 422 now
has a distinct `request_validation_failed` diagnostic. Twelve targeted tests
pass, including transfer resolution and validation-error classification.
each run covers one term, not exhaustive semantic search. Compatibility is also
accepted as a title screening signal. Incomplete search responses fail visibly.
After a complete file listing, PRs without non-test source changes are excluded
before commit/tree requests. Their IDs and reasons go to `discovery-skips.jsonl`,
outside the screened-record denominator; `discovery_skipped` reports the count.

Use `--resume-from <previous-artifact-directory>` with the same repository and
discovery arguments to reuse hash-verified routes and request missing responses.
This creates a new artifact directory and retains its own response receipts.
Cached listing pages freeze previously observed ordering; they are not refreshed.
Use a fresh run for current discovery. `--replay-from` remains strictly offline;
the two flags cannot be combined. Receipts are saved after each successful route.

Transport errors get at most three attempts (30-second timeout per attempt,
one- and two-second delays). HTTP errors, including rate limits, are not retried.
Eleven targeted tests pass for search, early exclusion, retry bounds, cache reuse,
partial output, classifications and hashes. Live search access remains unverified
in the agent environment; no new benchmark tasks are claimed.

### Candidate scope triage

Schema v2 preserves structural `eligible_candidate` and rejection reasons, adding
`classification` and `main_track_candidate`. Explicit formatter/linter/type-checker
names in titles are tagged `developer_tooling`; workflow-only changes or explicit
CI tool title signals are tagged `ci_tooling`. Other upgrades remain
`unclassified_upgrade`, never automatically labeled runtime compatibility fixes.
Only structurally eligible, unclassified records enter the provisional main track;
dependency scope and semantic changes still require manual review. Heuristics may
misclassify mixed upgrades; tooling records and raw evidence are retained.

Offline replay of the 20-PR HTTPX export recovered the original one structurally
eligible PR (#3651), classified it as developer tooling, and produced zero main
track candidates. Result: `.keel/upgradebench-mining/fa1ef3c25c9d4bb2951e66514327846f`.
Nine targeted tests pass. No Docker reproduction or ready-task claim follows.

### GitHub access diagnostics

Completed PR metadata is checkpointed after each candidate to `collected.jsonl`.
If collection fails later, completed candidates are screened with status `partial`,
`collection_complete: false`, and a nonzero exit code; ready tasks remain zero.
Recover an older interrupted run without network requests using:

```powershell
python examples/mine_upgradebench.py --repository psf/requests --limit 20 --pages 3 --replay-from .keel/upgradebench-mining/efc0c218b2324f39aabf8f8ffcab23af
```

Replay verifies every saved response against its receipt hash and stops at the
first missing request. This is offline recovery, not network resume. The real
interrupted run above recovered ten complete candidates, all rejected, into
`.keel/upgradebench-mining/249bbaae73cf486eb0acd462884eb184`.
Eight targeted tests pass, including partial-run preservation and replay integrity.

HTTP failures now record a safe `github_error` object in `mining.json`: HTTP
status, whether authentication was supplied, numeric quota/reset/retry headers,
category and a suggested next step. Tokens and remote error bodies are not
recorded. A 403 alone does not establish a rate-limit cause. Primary quota
exhaustion, secondary limits, invalid authentication and explicit permission
errors are distinguished where GitHub provides evidence; otherwise the cause
remains unconfirmed. The collector stops without automatic retries.

Follow https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api
for reset and retry guidance. Six targeted tests pass, including HTTP error
classification and credential/body redaction. This does not verify live access.

Collect a small real candidate export, verify exact local Git ranges against
receipts, curate task instructions and trusted acceptance bundles, and reproduce
base-fail/gold-pass in Docker. Start with a few successfully reproduced tasks
before increasing corpus size. Preserve all rejection and environment failures.

Full regression: 234 tests, 218 passed, 16 optional-dependency skips in the base interpreter, no failures. Compilation, CLI help and whitespace checks passed.
