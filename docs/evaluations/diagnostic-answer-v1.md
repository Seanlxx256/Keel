# Diagnostic answer micro-review

Evidence: `.keel/repair-review/diagnostic-answer-v1/results/source.json`,
`execution.json`, and `diagnostic-answer-execution-v2/results/report.json`.

| Attempt | Recorded tokens | Seconds | Observed outcome |
| --- | ---: | ---: | --- |
| Synthetic source control v1 | 964 | 11.937 | Concrete source answer, exact quote; patch not applied |
| Historical execution arm v1 | 6365 | 11.406 | Completion rejected; reason unclassified |
| Execution-only v2 | 5916 | 10.079 | Unknown with exact quotes, specific evidence gap, no edits |

Total 3 paid calls /13,245 recorded tokens. No full repair or acceptance run.
The source control summary incorrectly said Updated despite no patch application;
only its source reasoning was accepted. The v2 answer correctly distinguishes a
relevant formatter definition from evidence that this failing input traverses it.
It asks for exact verification/writeout source or an execution observation.

Manual judgment: supports source-answer protocol compliance and honest uncertainty
on these examples. Does not establish general accuracy, root cause, repair gain,
autonomous evidence acquisition or execution of a probe. Increasing allocation to
2048 enabled this complete reply; without the old finish reason, prior truncation
remains a hypothesis. The two executions are stochastic replies, not causal proof.

Next design: route unknown through shared bounded read-only evidence acquisition,
reusing existing source inspection and test-location navigation. Keep missing test
sources read-only. Reassess after fresh evidence; if execution remains necessary,
record that capability gap. Current runtime unknown still stops before writes.
