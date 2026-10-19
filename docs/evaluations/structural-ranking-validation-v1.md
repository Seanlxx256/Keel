# Experimental structural ranking validation

`compass.structural` uses personalized PageRank on indexed resolved calls and
combines original and graph ranks with fixed 2:1 reciprocal ranks (constant 60),
damping 0.85 and 30 iterations. It only reorders original candidates. Unresolved
calls are not invented; self-edges and duplicate pairs are ignored. Graphs beyond
200,000 edges or with no resolved edges retain original order with evidence.
This is not Aider's graph and not a complete Python call graph.

`Routing(ranking='code-aware-structure')` is an optional online switch; existing
defaults and code-aware behavior remain unchanged. The controlled experiment
reorders the exact saved original pool with identical source spans and packing:
100 output lines and 32 lines per region. No labels, training or new embeddings
enter the ranking function. Structural evidence remains inspectable.

## Frozen new-task experiment

Plan: `.keel/structural-validation/plan-v2/plan.json`.
Tasks: Requests 6028, Pytest 7571, Xarray 3993, Astropy 12907 and Django 16116.
These IDs are disjoint from recorded local exposure, including planned failures;
they are not five new repositories or verified training-unseen tasks. Selection
retains the seeded small-repository/Python/read-core eligibility bias.

Three arms: original Compass, same-pool structural ranking, and native Aider
0.86.2 ranked tags with the previously disclosed AST range adapter. Aider uses a
different native pool. Component scores do not prove whole-agent repair gains.
No weights will be tuned or failed tasks replaced after seeing these results.

Plan v1 is preserved. Plan v2 records an explicit pre-execution implementation
amendment for exposure inventory and resume receipts; tasks, datasets and ranking
policy were unchanged before any new task had a score.

## Runtime and resume

The runner reuses shared snapshot preparation, bounded embedding-index worker,
coverage gate, native Aider worker and scorer. A task child has a parent deadline
of 1,500 seconds, indexing 900 seconds and Aider 300 seconds. Completed baselines
are reused after source/index/dataset/packing checks. Completed task receipts and
dependent artifacts are hashed before whole-task reuse. Failed attempts and
partial scores are retained, never averaged as zero.

```powershell
Set-Location D:\keel
& 'D:/code/monocular_depth_estimation/.venv/Scripts/python.exe' examples/run_structural_validation.py --plan .keel/structural-validation/plan-v2/plan.json --output .keel/structural-validation/run-v1 --execute --resume
```

The preceding study installed the isolated Aider environment. Indexing requires
the configured local Ollama embedding model. No model substitutions or global
package changes are made. Incomplete baseline sweep directories are retained as
explicit blockers rather than overwritten; not all failure classes have automatic
recovery actions.

## Actual evidence

Existing retrieval tests and structural checks cover candidate preservation,
resolved-edge behavior, deterministic ordering and unchanged default routing.
A smoke check on four exposed indexes retained their 55-60 candidates and took
about 0.1-2.6 seconds, without evaluating relevance metrics or tuning parameters.

The first five-task run failed at snapshot fetch because this tool environment
routes GitHub requests to an unavailable proxy at 127.0.0.1:9. All five failure
receipts are retained in `.keel/structural-validation/run-v1/run.json`; quality
metrics remain null. No network settings or permissions were changed. Continue
in an ordinary network-enabled terminal using the same frozen plan and --resume.
The new ranking has not yet demonstrated a quality gain and is not the default.
