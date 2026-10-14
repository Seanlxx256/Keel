# Keel
A reliability runtime for long-horizon coding agent.

Keel is not a coding agent itself, but a governance layer built on top of generic agent harness,
targeting non-model failures in long coding tasks: timeout, reward hacking, premature termination and self-validation bias.

## Architecture
- Six-role isolated pipeline with DAG work-item scheduling
- External SQLite memory ledger
- GBDT early-stopping predictor
- 3-layer anti-cheat audit system

Integrates with **Compass**, the adaptive codebase retrieval MCP server.
