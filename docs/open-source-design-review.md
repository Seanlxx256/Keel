# Open-source mechanism review (2026-10-16)

Scope: primary documentation/repository/paper review only. No dependency installed,
external project benchmark reproduced, code imported or performance gain claimed.

| Source | Documented mechanism | Relevant experiment for Keel/Compass |
| --- | --- | --- |
| [mini-SWE-agent](https://mini-swe-agent.com/latest/) | Minimal single-agent loop, linear history, shell-based execution | Single-session baseline; do not copy shell access onto the unsandboxed host |
| [Agentless](https://github.com/OpenAutoCoder/Agentless) | Hierarchical file/function/edit localization, candidate repair, patch validation | Autonomous localization feeding bounded proposal generation; keep verifier independent |
| [Aider repo map](https://github.com/Aider-AI/aider/blob/main/aider/website/docs/repomap.md) | Compact symbols/signatures and dependency-graph ranking under a token budget | Build a bounded overview from existing symbol/import indexes; measure localization and cost |
| [SWE-agent tools](https://swe-agent.com/latest/config/tools/) | Inspection/editor tools and explicit environment state | Study observable tool state and edit feedback rather than repeatedly changing prose prompts |
| [Continue agent context](https://docs.continue.dev/ide-extensions/agent/context-selection) | Context selection using file content, definitions, imports and recent files | Inspect exact implementation before deciding whether another retrieval backend is needed |
| [AutoCodeRover paper](https://arxiv.org/abs/2404.05427) | Code-search APIs combining model reasoning with repository structure | Function/class-oriented reads instead of relying only on fixed line pages |

## Limits and priority

Published project scores use their own models, tools, tasks and budgets; do not
compare them directly to our development tasks. A shell-only agent has different
permissions from Keel; equal-access internal comparison must remain separate from
an external end-to-end baseline. Documentation inspection is not source-code audit.

The latest HTTPX traces already locate plausible files, but no edits are attempted.
An embedding/reranking replacement alone is therefore not a demonstrated fix.
Prioritize a simple equal-access session and an Agentless-style staged pipeline,
then test repo-map/structural reads separately. Preserve existing verifier,
audit, budgets and raw failures. Any borrowed implementation needs a pinned
revision and license review before incorporation.

## Retrospective reporting

Prior work preserved environment failures and model failures and never counted
HTTPX as repaired. However, repeated post-outcome adjustments to source windows,
tool contracts and prompts make old cases development cases. Passing host tests
does not prove a live-model fix. Role shape compatibility and truncated-page
semantics are deliberate contract changes, not unchanged strict protocol behavior.
Resume claims must distinguish mechanisms implemented from outcomes measured.
