# W8 ledger and memoization integration

Local file listing and literal searches now share a persistent content-keyed
observation cache, while each gateway session creates its own evidence IDs.
Arguments, repository identity and full content fingerprints participate in keys.
Pre/post fingerprints reject detected source races. Calls still charge tool
budget; content hashing remains work, and no measured latency or token savings
are claimed. Compass/MCP/model/verification/write operations are not cached.

Trusted orchestration can explicitly copy up to sixteen selected file/symbol
facts between gateways of the same Workspace, with recipient-owned IDs and
source provenance events. This API is not exposed to model actions. All selected
facts are validated before grants are made. Old copied observations remain
historical evidence after edits; they are not rewritten as fresh facts. Automatic
handoff selection in agent planning is not yet connected.

Validation on 2026-10-15:

- Five tests passed: cross-role cache reuse with recall isolation; add/edit/delete
  and limit invalidation; persistence and hit-budget enforcement; source changes
  during scanning; explicit grants and rejection of ungranted source IDs.
- `examples/memory_demo.py` passed all six checks, recording three cache hits,
  eight budgeted tool calls, and explicit handoff recall followed by fresh search
  after editing source. Artifacts:
  `.keel/memory-demo/9c2aeb3fe0ae43d4be390de90d5866b3`.
- Prior W6-7 user evidence: Docker isolation probe passed, and CPU model + Docker
  verifier passed all six end-to-end checks in 206.922 seconds / ten model calls.
  That artifact is `.keel/agent-smoke/05a197a463334265971eeda0c5e20763`.

Next W8 work: bounded evidence selection at actual role boundaries and measured
cache overhead on larger repositories. This milestone does not establish
whole-agent OS isolation, general model reliability, or UpgradeBench results.

Full regression before the final handoff test addition: 208 tests, 203 passed, 5 optional-dependency skips, no failures. Final gateway (4 tests) and memory (5 tests) suites also passed. Whitespace check passed.
