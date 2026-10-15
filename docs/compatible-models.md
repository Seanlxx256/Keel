# Compatible HTTP models for controlled comparisons

Keel supports an explicit `openai-compatible` Chat Completions adapter alongside
Ollama. It implements nonstreaming requests, structured/JSON output and reported
usage following the [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
and [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).
This does not establish compatibility with every vendor or model; no external
service has been called or selected by this implementation.

## Configuration and run

Copy `examples/model-compatible.example.json` to an ignored local file such as
`.keel/model-compatible.json`, replacing the endpoint and model placeholders.
Use the provider's exact base URL prefix (often ending in `/v1`); Keel appends
`/chat/completions`. Only credential environment-variable names belong in JSON,
never key values. Inline keys and unknown compatible settings are rejected
before the suite writes its manifest. Preparation needs no credentials.

Set a key in the current PowerShell session without displaying it:

```powershell
$modelSecret = Read-Host "Model API key" -AsSecureString; $env:KEEL_MODEL_API_KEY = [System.Net.NetworkCredential]::new("", $modelSecret).Password
```

Prepare only:

```powershell
python examples/run_agent_baseline.py --reproduction .keel/upgradebench-reproduction/cb311b9aad5c466f8c360ec27e4b38f9 --strategy proposal --group real_compatibility --dependency-evidence --model-config .keel/model-compatible.json
```

After selecting the service/model, add `--execute` to run. This sends the goal,
source windows and collected dependency evidence to that configured service.
It uses the same Docker acceptance and suite budgets; proposal mode makes one
completion call per task without automatic retries. Applicable charges and data
handling depend on that service, not a ChatGPT subscription or this tool.
Clear the session credential afterward with `Remove-Item Env:KEEL_MODEL_API_KEY`.

## Adapter contract

- Required configuration: `provider`, `name`, `base_url`. Optional:
  `api_key_env` (default `KEEL_MODEL_API_KEY`), `response_mode`,
  `token_limit_field`, and `temperature`.
- `response_mode: json_object` is default. The output schema is included in the
  prompt; gateway/patch validation remains authoritative. `json_schema` explicitly
  requests strict server-side output and requires a root object; use JSON object
  mode for the union-based agent action protocol. Unsupported schemas fail
  visibly, without a hidden format fallback or extra paid call.
- `max_completion_tokens` is the default output-limit field; set
  `token_limit_field: max_tokens` only for a service requiring the legacy field.
  Temperature is omitted unless configured because support varies. For reasoning
  models the completion budget can include hidden reasoning, so equal numeric
  limits do not guarantee equal visible output or work performed.
- Remote endpoints require HTTPS; plain HTTP is limited to literal loopback
  hosts. Credentials in URLs, query parameters and fragments are rejected.
  Redirects are not followed with bearer credentials. TLS verification is not
  disabled. HTTP/network errors report status/type, not response bodies, headers
  or key values. No live request is made just to enumerate remote models.
- A completion must have one assistant text response, finish reason `stop`, no
  refusal or remote tool call, and consistent nonnegative integer
  prompt/completion/total usage. Truncation and malformed responses fail closed.
  Valid reported usage on a rejected completion is charged to agent/proposal
  budgets. Errors without usable usage remain unknown cost, not proven free.
  Tokens are not a monetary spending cap or vendor invoice reconciliation.

Reported model IDs and optional system fingerprints appear in model trace
metadata and suite metrics. The remote suite identity is explicitly unverified:
configuration plus vendor-reported labels cannot pin model weights or guarantee
backend stability. Endpoint/protocol/temperature defaults also differ from
local Ollama, so describe such a run as a controlled provider/model comparison,
not an isolated weights-only experiment or reproducible weight digest.

## Verification

Seven offline adapter tests cover authentication placement, response formats,
legacy token field, caller-message immutability, usage validation, incomplete
responses, redacted HTTP errors, no retries/redirects, missing credentials,
safe configuration, rejected-response billing and a full factory-to-runtime
proposal/edit/acceptance flow using a mocked transport. Suite tests verify that
preparation does not read credentials and inline keys never reach output files.
No live vendor interoperability, stronger-model repair, latency/cost advantage
or benchmark success is claimed. Service URL and exact model selection remain
operator inputs.
