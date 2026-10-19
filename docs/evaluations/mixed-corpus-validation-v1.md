# Mixed text corpus development experiment v1

This is a new protocol on the five exposed structural-validation tasks. It does
not rewrite the original experiment or remove its two scope exclusions. It tests
whether admitting documentation/configuration helps under the same output budget.
It is not held-out evidence, official repair scoring or a comparison with complete
Aider/Serena/CocoIndex products.

## Fixed corpus and retrieval policy

`compass.text_corpus` indexes regular Git-tracked UTF-8 files ending in .py, .md,
.rst, .toml, .ini, .cfg, .yaml, .yml or .json, at most 1 MB per file. Symlinks and
submodules are not dereferenced. Unsupported types, excessive size and encoding
omissions are recorded. Candidate spans are consecutive, nonoverlapping 32-line
windows, with exact source path and line positions. This is text chunking, not
syntax-aware document parsing or a semantic understanding of configuration.

It uses native SQLite FTS5 BM25 with the shared identifier tokenizer. Query terms
are deduplicated in original order and capped at 128; output is at most 100
candidates. Ties use path and start line. No labels enter indexing or retrieval.
It does not call a model or embedding service. Per-file SQLite transactions permit
checkpoint reuse after interruption. Root/policy mismatch, stale source bytes and
incomplete indexes are rejected. Corpus and metric snapshots are checked.

## Four predeclared arms

1. Saved Python-only Compass hybrid candidates, rescored without modification.
2. Python windows from the new lexical index.
3. All supported windows from that index.
4. Fixed alternate interleave of saved Compass and non-Python text candidates,
   Compass first, deduplicating exact spans before shared context packing.

Arms 2 and 3 share the same mixed-index BM25 document statistics; the kind filter
is the changed variable. This isolates admitted candidates, not the full effect
of rebuilding a Python-only corpus's IDF. Arms 1 and 2 differ in ranking and
chunking and cannot isolate corpus expansion. The complement arm changes both
candidate acquisition and order. No weight or parameter alternatives are searched.

All arms use 100 output lines and at most 32 lines per region. This is not an
equal-token budget: long lines can consume more tokens. A saved Python-only
control remains a limited-corpus control on Xarray/Astropy and retains its original
`unindexed_reference_files` status in the report, rather than being relabeled a
successful original run. References and denominators are unchanged.

## Execution and artifacts

Plan: `.keel/mixed-corpus/plan-v1/plan.json`. Run: `.keel/mixed-corpus/run-v1`.
The plan binds task data, closed original run, saved candidates and implementation
hashes before mixed-corpus scores. Per-task process deadline is 600 seconds;
index deadline is 300 seconds. Results have input/source/index hashes and explicit
omissions. Successful results can be resumed after checking receipt, index and
snapshot identities; prior failed receipts are archived separately.

```powershell
python examples/run_mixed_corpus_validation.py --plan .keel/mixed-corpus/plan-v1/plan.json --output .keel/mixed-corpus/run-v1 --execute --resume
```

No model key, model download or remote service is needed when snapshots and the
main environment are present. This entry point does not change Keel's default
tools or Compass's default retrieval. A future MCP integration and end-to-end
repair comparison would be separate increments after quality and safety review.

## Completed results

All five tasks completed under this new protocol. Receipt and index hashes were
verified, and all 20 arm prediction/metric sets reproduced. Mixed-index coverage
includes every reference file, without changing original Python-only exclusions.
Audit: `.keel/mixed-corpus/run-v1/acceptance.json`.

| Arm, same five tasks | Mean line recall | Mean line precision | Mean file hit rate |
|---|---:|---:|---:|
| Saved Python-only Compass control | 8.002% | 67.80% | 52.00% |
| Python text windows | 6.023% | 47.20% | 38.00% |
| Mixed text windows | 4.410% | 26.40% | 29.00% |
| Compass plus non-Python text | 4.758% | 40.40% | 34.00% |

Mixed lexical retrieval has zero wins, two ties and three losses versus Python
lexical retrieval. Complementary interleave loses on all five tasks versus saved
Compass. These five-task means cannot be compared directly to earlier three-task
means: the task populations differ. The two formerly excluded tasks appear as
explicit limited-corpus controls only in this separate new protocol.

Output shows displacement: Xarray's mixed lexical context starts with roadmap,
setup and contribution text; Django starts with contributor CI configuration.
Requests' complementary context inserts an FAQ, lowering precision from 79% to
53%. This demonstrates a failure of this fixed ranking/mixing policy, not that
documentation is inherently unhelpful or every mixed retriever must fail.

A real completed-run resume reused all five receipts. Task log hashes remained
unchanged, confirming no worker relaunch. No generation or embedding calls were
made. Ten related text-index/interleave/external-comparison checks passed.

Decision: do not enable automatic text mixing by default. Retain the optional
capability and investigate explicit agent-directed text search as a separately
evaluated tool. Future routing needs new frozen evidence, not per-task tuning
against these exposed development scores.
