# Proposal context admission

This opt-in policy replaces percentage-based byte headroom for patch proposals.
Other stages retain their existing policies. Defaults and old frozen runs remain
unchanged. Use `--proposal-context-policy examples/proposal-context-policy.json`
with run_swebench_task, or agent.proposal_context_policy in a runtime config.
Do not combine with legacy proposal_context_hard_bytes.

The example declares GPT-5.4's documented1,050,000-token context, but limits each
proposal to60,000estimated input tokens including a1,024-token safety reserve.
The byte ceiling131,072 is an independent resource guard. None of these example
operational budgets is experimentally optimal. Verify model/deployment limits
before reuse with a different model. Source: [GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4).

For each proposal, available input is the minimum of:

- declared model context minus maximum requested output;
- per-request input allowance;
- remaining global token budget minus maximum requested output.

Estimated input plus safety must fit this amount. Byte overflow and token/model
capacity are distinct errors. Global depletion stops without spending source
reselections; output is not silently reduced. Exact source text, current logs and
permissions are retained. Existing lossless repacking still starts at byte soft
target max_context_bytes. The policy does not score evidence relevance or delete
information to fit, and does not guarantee the provider will accept an estimate.

## Counting and fallback

Default estimator uses serialized UTF-8 bytes conservatively as estimated tokens.
This is deliberately coarse; its method is emitted in traces, not reported as
exact tokenization. The full schema and message text participate in estimation.
Provider framing can differ, so the safety allowance is always separate.

Optional offline tiktoken support uses `local_tokenizer` naming a trusted local
JSON with name, pat_str, mergeable_ranks (base64 token bytes to integer ranks),
and special_tokens. Install optional dependency `keel-runtime[token-counting]`
and provision an encoding compatible with the deployment separately. No runtime
model guessing, HTTP token-count call or tokenizer asset download is performed.
Missing dependency/file or invalid resource falls back visibly to conservative
bytes. The encoding resource is capped at20MB and its hash is traced when used.
This encoding must be verified by the operator; arbitrary vocabulary does not
provide a valid model count.

Local tokenization is an estimate, especially for message framing and schema.
The official exact counting API describes Responses inputs; this project still
uses Chat Completions and does not silently migrate transport or claim exactness.
See [counting tokens](https://developers.openai.com/api/docs/guides/token-counting).

## Observability and calibration

`proposal_token_admitted` logs the estimator, reserves, effective limits and policy
hash. Rejected admissions log the reason; no provider call is made on denial.
The compatible model adapter preserves actual prompt/completion usage metadata.
`proposal_token_estimate_observed` binds prediction to actual input usage, model,
policy and tokenizer identities. `context_budget.calibration_report(events)`
groups these observations and reports sample count, p95 actual/estimate ratio,
maximum underestimate and under-reserved samples. It does not change policy.
Do not mix models, tokenizers or policies, infer USD costs from total tokens alone,
or choose a smaller margin solely because one known task passes.

## Validation scope

Unit tests cover independent byte/model/per-call/global bounds, output/safety
reservation, explicit fallback, offline constructor boundary and calibration
grouping. Offline tokenizer constructor tests use a stub; no real tokenizer is
installed in the current developer interpreter. Stored full-repair-v3 first
reselection replay fits with unchanged evidence under the example policy. These
are zero-model checks, not fresh repair acceptance or measured cost improvement.
