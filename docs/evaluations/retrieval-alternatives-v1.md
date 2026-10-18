# External retrieval comparison (development sample)

Measured 2026-10-18. Artifact: `.keel/retrieval-alternatives/v4/comparison.json`.
Earlier v1-v3 attempts are retained, including adapter failures; this is not a
first-attempt or held-out score. No model calls were made.

## Protocol

Same three SWE-Explore repository snapshots and issue queries as historical
`.keel/swe-public/bdb1b28a48574f5fa371d7f53271854e/result.json`.
Output budget: at most 100 unique source lines, at most 32 lines per symbol.
Labels are read only by the scoring stage, never passed to external workers.
Source fingerprints are checked after retrieval. Invalid ranges fail scoring.

Compass numbers are cached historical T1 measurements, not a new execution of
the current implementation. External lexical libraries share Compass chunks
and analyzer; they measure ranking components, not standalone coding agents.

Serena 2.0.0 uses its actual Pyright-backed `FindSymbolTool`. A fixed adapter
extracts dotted/camel/snake identifiers from issue text (at most eight queries),
performs substring symbol searches, and preserves returned order. This is not a
natural-language semantic ranker or an LLM-driven Serena agent. File/package/
module navigation containers are excluded. Up to 100 matches per query are
allowed, followed by the common line-budget packer. All raw observations are
saved. The installed cached Pyright executable was selected through Serena's
`ls_base_cmd` setting; no third-party package was patched.

## Results

Line recall (%):

| Task | Compass code-aware, historical | Serena symbol adapter | SQLite FTS5 |
|---|---:|---:|---:|
| Flask 5014 | 3.19 | 10.22 | 0.00 |
| Requests 1724 | 4.62 | 0.00 | 0.00 |
| Seaborn 3069 | 1.67 | 2.06 | 0.19 |
| Mean, same three tasks | 3.16 | 4.09 | 0.06 |

Serena wins two tasks and loses one. Identifier navigation is useful but does
not replace issue-aware ranking: early substring matches can consume the
budget before relevant definitions. These observations do not establish an
overall winner, coding-task success, or statistically reliable improvement.

The denominator is trajectory read-core, often whole files: 626, 1385, and
2627 core lines. Under a 100-line budget, theoretical recall ceilings are
15.97%, 7.22%, and 3.81%. These percentages are not repair success rates.

## Other open-source candidates and execution limits

- [BM25S](https://github.com/xhluca/bm25s): actual optional library adapter added.
- [rank_bm25](https://github.com/dorianbrown/rank_bm25): actual BM25Okapi adapter added.
- [SQLite FTS5](https://www.sqlite.org/fts5.html): executed the real installed engine.
- [Serena](https://github.com/oraios/serena): executed actual installed symbol tools.
- [CocoIndex Code](https://github.com/cocoindex-io/cocoindex-code): researched as
  an AST/embedding semantic-search alternative; not installed or measured.

The pip attempt to install BM25S/rank_bm25 in the restricted execution
environment failed to obtain distributions. They are explicitly unavailable,
not assigned zero recall. Their quality and CocoIndex's quality remain unknown.
Installation log: `.keel/retrieval-baselines/install.log`.

To install the two lexical libraries into an isolated target directory and
repeat from a network-enabled user terminal:

```powershell
& ./scripts/test-retrieval-alternatives.ps1
```

Use `-Python` to select an interpreter with Compass dependencies and
`-PyrightCommand` to select an existing language-server executable if Serena's
default launcher cannot start. The script does not modify global packages or
credentials. Resolved engine versions are saved with scores. CocoIndex is not
silently installed by this command and is not included in its measured engines.

Validation: 31 Python tests passed across retrieval alternatives, selection
ablation and retrieval; PowerShell runner syntax parsed successfully. Real
Serena/SQLite runs complement these tests. Installation automation has not been
successfully network-tested in this restricted session.
