# Keel local OTLP trace export

Keel writes one compact OTLP/JSON ExportTraceServiceRequest record to
`spans.otlp.json` when a run finishes. A root run span contains sequential role
spans, with child model, agent gateway, and verification command spans. Existing
JSONL events carry matching trace IDs, span IDs, and sampled flags. Timestamps
use a wall-clock epoch anchor plus monotonic elapsed time.

This dependency-free file exporter follows the OTLP JSON and file format:

- https://opentelemetry.io/docs/specs/otlp/
- https://opentelemetry.io/docs/specs/otel/protocol/file-exporter/

It is not an OpenTelemetry SDK implementation, network exporter, or distributed
context bridge. A live Collector ingestion test remains outstanding. Remote MCP
server internals, direct Workspace operations outside the gateway, and HTTP model
server internals are not individually instrumented. Hard termination can prevent
final file export; append-only event logs remain the durable progress record.

Exported metadata uses an explicit allowlist. Goals, source, prompts, command
arguments, and remote error payloads are excluded from this file. Existing ledger
and JSONL artifacts retain their usual contents. Calls missing a finish event
are ended with ERROR and `keel.interrupted=true` at role exit. Failed or denied
operations receive ERROR; export I/O failure is reported independently without
replacing the task result.

Validation on 2026-10-15:

- Three telemetry tests passed: span hierarchy/log correlation, actual runtime
  exception cleanup, and visible export failure independent of task outcome.
- Twelve agent tests passed, including an actual scripted agent run checking
  six model spans, three tool spans, one verification span, and complete closure.
- Nine runtime tests passed before the broader regression.
- `python examples/demo.py` passed with seven closed spans and independent
  command verification. Artifacts: `.keel/demo-runs/aeaa98b8abcd47dc912a03021481320c`.
- User separately reported all five MCP client tests passing, including actual
  Compass stdio discovery/call/schema-error recovery/shutdown. This supersedes
  the earlier restricted-environment failure as user-machine evidence; it does
  not establish host sandbox isolation.

W6-7 still requires live sandbox and real-model end-to-end validation.

Full base-interpreter regression: 199 tests, 194 passed and 5 optional-dependency skips; no failures. The final telemetry and agent assertions were also rerun successfully.
