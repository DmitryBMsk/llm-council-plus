# Generation limits and incomplete answers

Each model call stores `finish_reason`, `native_finish_reason`, `generation_id`
(when supplied by OpenRouter), `effective_max_tokens`, configured reasoning controls,
`completion_status`, `truncated`, and provider usage when supplied. These fields travel
through council stages, SSE, and saved conversation results. No API credentials or
request payloads are included in this metadata.

`truncated: true` means the provider explicitly reported `length` or `max_tokens`.
A missing finish reason produces `truncated: null` and `completion_status: unknown`.
Token usage reaching the configured limit alone is a suspicion, not confirmation.
A token-limited answer with no visible content is `truncated_empty`; reasoning can
consume the entire output allowance. It remains distinguishable from transport
errors and ordinary empty responses. No automatic continuation or truncation retry
is performed. Existing 429 retry and chairman transport-error fallback behavior
is unchanged; truncation itself does not trigger them.

## Settings

Administrators can edit generation limits through the existing runtime settings
API (`PATCH /api/settings`), with the same permissions, export/import, reset, audit,
and persistence behavior as other global settings. Existing installations retain
8192 output tokens per call, including title generation. Ollama now receives that
explicit limit through `options.num_predict`.

```json
{
  "generation_limits": {
    "stage1": {"max_tokens": 8192},
    "stage2": {"max_tokens": 4096},
    "stage3": {"max_tokens": 16384},
    "title": {"max_tokens": 512},
    "continuation": {"max_tokens": 8192}
  },
  "model_generation_limits": {
    "anthropic/claude-fable-5.1": {
      "stage1": {"max_tokens": 16384, "reasoning_effort": "medium"}
    }
  }
}
```

This is an example, not an automatic limit increase. Larger output limits can
require more available provider credit for in-flight requests, even when the final
answer is short. Select values deliberately and monitor provider usage and balance.

- Allowed stage keys: `stage1`, `stage2`, `stage3`, `title`, `continuation`.
  Chairman fallback uses `stage3`; internal search optimization uses the default.
- `max_tokens`: integer 128–65536. The application ceiling does not assert that any
  particular model supports that many output tokens. Provider limits still apply.
- `reasoning_max_tokens`: optional integer 1024–65535, strictly below `max_tokens`.
  This conservative lower bound covers Anthropic's documented minimum.
- `reasoning_effort`: optional `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, or
  `max`. Availability depends on the selected model and upstream provider.
- Set either reasoning control, never both. Omit/null both to preserve provider
  default reasoning behavior; the application sends no `reasoning` object then.
- Exact model ID plus stage overrides the entire global stage budget. Omitted
  model stages inherit global settings; omitted global stages use 8192 with no
  explicit reasoning control. Updating either map replaces that map, so send all
  entries to preserve. An empty `model_generation_limits` removes all overrides.

OpenRouter receives `max_tokens` and optional `reasoning.max_tokens` or
`reasoning.effort`. With explicit reasoning configured, provider routing requires
parameter support (`provider.require_parameters: true`). Because this checks all
supplied parameters, explicit reasoning also omits the optional stage temperature
and uses the provider sampling default. This keeps reasoning-only models that do
not support temperature eligible. With reasoning controls unset, the configured
stage temperature is sent as before. This cannot guarantee
that every upstream model honors an exact reasoning sub-budget: some models use
adaptive thinking and may ignore explicit reasoning token budgets. Provider
validation errors remain visible; the app never silently increases the output cap
or silently retries with different reasoning controls.

The Ollama adapter supports output limits only. Explicit reasoning settings return
a configuration error before any inference request; clear them for Ollama models.
Ollama's `think` support varies by model and is not mapped to OpenRouter reasoning
settings. Both reasoning and visible text count toward the output allowance.

## Verification and references

Run `python -m pytest backend/tests/test_generation_controls.py` for provider
response fixtures, stage/model precedence, validation boundaries, explicit
reasoning payloads, empty truncated ranking preservation, and Ollama stage limits.
These tests make no paid model calls.

- [OpenRouter reasoning controls](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
- [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)
- [Ollama chat API](https://docs.ollama.com/api/chat)
- [Ollama thinking](https://docs.ollama.com/capabilities/thinking)
