# Local semantic retrieval and T2 integration check

The operator imported two GGUF models into Ollama and verified a basic chat response. A subsequent project-side check exercised real embeddings, tree-sitter extraction, LanceDB storage, and the T0/T1/T2 retriever. This is a three-function synthetic smoke fixture, not public-data retrieval quality evidence.

## Configuration

- Endpoint: `http://localhost:11434`.
- Embeddings: `keel-embed`, imported from `Qwen3-Embedding-0.6B-Q8_0.gguf`; observed output dimension: 1,024.
- Chat: `keel-chat`, imported from `qwen2.5-coder-3b-instruct-q4_k_m.gguf`.
- Parser/storage: real `tree-sitter` and `lancedb`.
- Fixture: three functions across two files; target `invoice_total`.
- T2 limits: 180 seconds, four model calls, 60 tool calls, and 20,000 tokens; maximum four exploration steps.

| Model tag | Observed Ollama manifest digest |
| --- | --- |
| `keel-chat:latest` | `d8e45768208394715b5febaea6dfe20f1b9d533d27044c2c0fbee4ef9410915a` |
| `keel-embed:latest` | `8b752ab34efb5f17a84567801ec213e5d2c2da504b5501775cec3588258cc13d` |

These are local Ollama manifest digests, not independently verified upstream GGUF checksums.

## Observations

| Mode | Outcome | Tool calls | Model calls | Chat tokens | Vector queries | Retrieval seconds |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| T0 | Exact target found | 1 | 0 | 0 | 0 | 0.000776 |
| T1 | Target ranked first among three symbols | 2 | 0 | 0 | 1 | 2.289404 |
| T2 | Completed; target selected | 4 | 3 | 1446 | 1 | 16.836879 |

The separate embedding probe returned two finite, nonzero, 1,024-dimensional vectors. The chat API probe returned JSON with provider token accounting. T2 completed a real bounded exploration and returned `invoice_total` using three model calls and 1,446 reported prompt/output tokens.

Timing is a single observation with uncontrolled model loading and caches. Token counts exclude embeddings. GPU utilization was not established by this check. The fixture has only three candidates; hitting its target cannot establish retrieval quality, performance improvement, official benchmark parity, or valid routing thresholds.

Full local evidence: `.keel/live-model-checks/280845224a414be6a16a04b1871b38de/validation.json`. Its `synthetic` flag is true and `public_benchmark_verified` is false. The next experiment requires real SWE-Explore instances and their verified base-commit snapshots, with preregistered repository splits and fixed model configurations.
